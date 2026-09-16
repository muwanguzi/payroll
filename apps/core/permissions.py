"""Thin role helpers for view-level access control (Recommendation 6.8).

The pay-run workflow is a four-officer chain: Head of Human Capital prepares,
Chief People Officer reviews, Chief Audit Officer approves, Chief Finance
Officer disburses.
"""

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin


def in_role(user, *role_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=role_names).exists()


class RoleRequiredMixin(UserPassesTestMixin):
    required_roles: tuple = ()

    def test_func(self):
        return in_role(self.request.user, *self.required_roles)


class EmployeeEditMixin(RoleRequiredMixin):
    required_roles = tuple(settings.ROLES_EMPLOYEE_EDIT)


class PrepareRunMixin(RoleRequiredMixin):
    required_roles = tuple(settings.ROLES_PREPARE)


class ReviewRunMixin(RoleRequiredMixin):
    required_roles = tuple(settings.ROLES_REVIEW)


class ApproveRunMixin(RoleRequiredMixin):
    required_roles = tuple(settings.ROLES_APPROVE)


class DisburseRunMixin(RoleRequiredMixin):
    required_roles = tuple(settings.ROLES_DISBURSE)
