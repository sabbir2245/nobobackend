from rest_framework import permissions

class IsFarmer(permissions.BasePermission):
    """
    Allows access only to users with the 'farmer' role.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'farmer'


class IsCustomer(permissions.BasePermission):
    """
    Allows access only to users with the 'customer' role.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'customer'


class IsAdminUser(permissions.BasePermission):
    """
    Allows access only to users with the 'admin' role or is_staff.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and (request.user.role == 'admin' or request.user.is_staff)


class IsDeliveryman(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'deliveryman'


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner.
        if hasattr(obj, 'farmer'):
            return obj.farmer == request.user
        if hasattr(obj, 'customer'):
            return obj.customer == request.user
        return False
