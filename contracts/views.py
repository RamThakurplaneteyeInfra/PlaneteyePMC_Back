from decimal import Decimal, InvalidOperation, DivisionByZero

from django.utils.dateparse import parse_date
from django.db.models import Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Contract
from .serializers import ContractSerializer


def _get_role_from_request(request) -> str | None:
    """
    Simple role extraction (temporary).
    Requirement says: use request.data['role'] for now.

    We also support:
    - query param: ?role=CEO (helps for GET)
    - header: X-Role: CEO
    """
    role = None
    try:
        role = request.data.get("role")
    except Exception:
        role = None
    if not role:
        role = request.query_params.get("role") or request.headers.get("X-Role")
    return role


class ContractViewSet(viewsets.ModelViewSet):
    """
    Contract workflow endpoints.

    Endpoints:
    - POST   /api/contracts/                 -> Billing Site Engineer creates (status=pending)
    - GET    /api/contracts/                 -> Dashboard: ONLY approved contracts
    - GET    /api/contracts/all/             -> Admin view: all contracts (CEO only for now)
    - POST   /api/contracts/{id}/approve/    -> CEO approves and triggers calculations
    - POST   /api/contracts/{id}/reject/     -> CEO rejects
    - GET    /api/contracts/summary/         -> Dashboard totals (ONLY approved)
    """

    queryset = Contract.objects.all()
    serializer_class = ContractSerializer
    # Using role from request (temporary). Do not require auth for now.
    permission_classes = [AllowAny]

    # ---- Swagger schemas (fix DecimalField showing as string in Swagger UI) ----
    # drf-yasg (Swagger 2.0) often models Decimal as "string". Swagger UI then
    # refuses numeric input. We override request bodies to accept "number".
    _contract_create_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name", "original_contract_value", "created_by"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "original_contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=1000000.0),
            "approved_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=50000.0),
            "pending_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=25000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )

    _contract_update_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="Billing Site Engineer"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
            "original_contract_value": openapi.Schema(type=openapi.TYPE_NUMBER, example=1000000.0),
            "approved_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=50000.0),
            "pending_vo": openapi.Schema(type=openapi.TYPE_NUMBER, example=25000.0),
            "created_by": openapi.Schema(type=openapi.TYPE_STRING, example="Billing SE 1"),
        },
    )

    _ceo_action_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="CEO"),
        },
    )

    _ceo_project_action_schema = openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["role", "project_name"],
        properties={
            "role": openapi.Schema(type=openapi.TYPE_STRING, example="CEO"),
            "project_name": openapi.Schema(type=openapi.TYPE_STRING, example="Project Alpha"),
        },
    )

    def get_queryset(self):
        """
        Filtering:
        - project_name: partial match
        - date: filter by created_at date (YYYY-MM-DD)

        For list():
        - return ONLY approved contracts
        """
        qs = Contract.objects.all()

        project_name = self.request.query_params.get("project_name")
        if project_name:
            qs = qs.filter(project_name__icontains=project_name)

        date_str = self.request.query_params.get("date")
        if date_str:
            d = parse_date(date_str)
            if d:
                qs = qs.filter(created_at__date=d)

        # Default list endpoint returns approved only (dashboard requirement)
        if self.action == "list":
            qs = qs.filter(status=Contract.Status.APPROVED)

        return qs.order_by("-created_at")

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve single contract.
        For dashboard: only return approved contracts.
        For CEO/admin: can retrieve any contract via /api/contracts/all/{id}/ or by checking role.
        """
        instance = self.get_object()
        
        # If not CEO and contract is not approved, return 404 (hide unapproved contracts)
        role = _get_role_from_request(request)
        if role != "CEO" and instance.status != Contract.Status.APPROVED:
            return Response(
                {"detail": "Contract not found or not approved."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        """
        Dashboard list: ONLY approved contracts.
        Returns clean structured response format.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)

        def clean(item):
            return {
                "project_name": item["project_name"],
                "original_contract_value": item["original_contract_value"],
                "approved_vo": item["approved_vo"],
                "approved_vo_percentage": item["approved_vo_percentage"],
                "revised_contract_value": item["revised_contract_value"],
                "pending_vo": item["pending_vo"],
                "status": item["status"],
            }

        data = [clean(x) for x in serializer.data]
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    @swagger_auto_schema(
        operation_description="Create contract (Billing Site Engineer). Status is forced to pending.",
        request_body=_contract_create_schema,
        responses={201: ContractSerializer, 400: "Validation Error", 403: "Forbidden"},
    )
    def create(self, request, *args, **kwargs):
        """
        Billing Site Engineer creates contract.
        Business rule: status is forced to pending.

        Permission (simple): request.data['role'] must be 'Billing Site Engineer'
        """
        role = _get_role_from_request(request)
        if role != "Billing Site Engineer":
            return Response(
                {"detail": "Only Billing Site Engineer can create contracts (role='Billing Site Engineer')."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Explicitly set status to PENDING (prevent any auto-approval)
        contract = serializer.save(status=Contract.Status.PENDING)
        headers = self.get_success_headers(serializer.data)
        return Response(self.get_serializer(contract).data, status=status.HTTP_201_CREATED, headers=headers)

    @swagger_auto_schema(
        operation_description="Update contract (Billing Site Engineer). Approved contracts cannot be edited.",
        request_body=_contract_update_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden"},
    )
    def update(self, request, *args, **kwargs):
        """
        Billing Site Engineer can update while not approved.
        (Simple version) role check using request.data['role'].
        """
        role = _get_role_from_request(request)
        if role != "Billing Site Engineer":
            return Response(
                {"detail": "Only Billing Site Engineer can update contracts."},
                status=status.HTTP_403_FORBIDDEN,
            )

        instance = self.get_object()
        if instance.status == Contract.Status.APPROVED:
            return Response(
                {"detail": "Approved contracts cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="all")
    def all_contracts(self, request):
        """
        Admin view: return all contracts.
        Simple permission: only CEO.
        """
        role = _get_role_from_request(request)
        if role != "CEO":
            return Response({"detail": "Only CEO can view all contracts."}, status=status.HTTP_403_FORBIDDEN)

        qs = self.filter_queryset(Contract.objects.all().order_by("-created_at"))
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="approve")
    @swagger_auto_schema(
        operation_description=(
            "CEO approves the latest PENDING contract for the given project_name."
        ),
        request_body=_ceo_project_action_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"},
    )
    def approve(self, request):
        """
        Approve by project_name (instead of id).
        Picks the latest PENDING contract for that project.
        """
        role = _get_role_from_request(request)
        if role != "CEO":
            return Response({"detail": "Only CEO can approve contracts."}, status=status.HTTP_403_FORBIDDEN)

        project_name = request.data.get("project_name") if hasattr(request, "data") else None
        if not project_name:
            return Response({"detail": "project_name is required."}, status=status.HTTP_400_BAD_REQUEST)

        contract = (
            Contract.objects.filter(project_name__iexact=project_name, status=Contract.Status.PENDING)
            .order_by("-created_at")
            .first()
        )
        if not contract:
            return Response(
                {"detail": "No pending contract found for this project_name."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Reuse existing approve logic by calling the same calculation block
        try:
            original = Decimal(contract.original_contract_value)
            approved_vo = Decimal(contract.approved_vo)
            revised = original + approved_vo
            approved_pct = float((approved_vo / original) * Decimal("100"))
        except (InvalidOperation, DivisionByZero):
            return Response(
                {"detail": "Cannot calculate values. Ensure original_contract_value > 0 and numbers are valid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        contract.revised_contract_value = revised
        contract.approved_vo_percentage = approved_pct
        contract.status = Contract.Status.APPROVED
        contract.approved_by = "CEO"
        contract.save(
            update_fields=[
                "revised_contract_value",
                "approved_vo_percentage",
                "status",
                "approved_by",
                "updated_at",
            ]
        )

        return Response(self.get_serializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="reject")
    @swagger_auto_schema(
        operation_description="CEO rejects the latest PENDING contract for the given project_name.",
        request_body=_ceo_project_action_schema,
        responses={200: ContractSerializer, 400: "Bad Request", 403: "Forbidden", 404: "Not Found"},
    )
    def reject(self, request):
        """
        Reject by project_name (instead of id).
        Picks the latest PENDING contract for that project.
        """
        role = _get_role_from_request(request)
        if role != "CEO":
            return Response({"detail": "Only CEO can reject contracts."}, status=status.HTTP_403_FORBIDDEN)

        project_name = request.data.get("project_name") if hasattr(request, "data") else None
        if not project_name:
            return Response({"detail": "project_name is required."}, status=status.HTTP_400_BAD_REQUEST)

        contract = (
            Contract.objects.filter(project_name__iexact=project_name, status=Contract.Status.PENDING)
            .order_by("-created_at")
            .first()
        )
        if not contract:
            return Response(
                {"detail": "No pending contract found for this project_name."},
                status=status.HTTP_404_NOT_FOUND,
            )

        contract.status = Contract.Status.REJECTED
        contract.approved_by = "CEO"
        contract.save(update_fields=["status", "approved_by", "updated_at"])
        return Response(self.get_serializer(contract).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """
        Dashboard summary totals for ONLY approved contracts:
        - Original Contract Value
        - Approved VO(s)
        - Revised/Remeasured Contract Value
        - Potential/Pending VO(s)
        """
        qs = self.get_queryset().filter(status=Contract.Status.APPROVED)
        totals = qs.aggregate(
            original_contract_value=Sum("original_contract_value"),
            approved_vo=Sum("approved_vo"),
            revised_contract_value=Sum("revised_contract_value"),
            pending_vo=Sum("pending_vo"),
        )

        # Normalize None -> 0
        def n(v):
            return v if v is not None else Decimal("0")

        return Response(
            {
                "original_contract_value_total": n(totals["original_contract_value"]),
                "approved_vo_total": n(totals["approved_vo"]),
                "revised_contract_value_total": n(totals["revised_contract_value"]),
                "pending_vo_total": n(totals["pending_vo"]),
            },
            status=status.HTTP_200_OK,
        )

# Create your views here.
