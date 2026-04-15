from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import BasicAuthentication
from .serializers import UserSerializer

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [BasicAuthentication]  # Force basic auth only

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
