from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import UserSerializer

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated] # Only authenticated users can access this

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
