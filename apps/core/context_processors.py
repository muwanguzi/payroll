from django.conf import settings


def roles(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"user_roles": set()}

    names = set(user.groups.values_list("name", flat=True))
    su = user.is_superuser

    def has(*roles):
        return su or bool(set(roles) & names)

    return {
        "user_roles": names,
        # individual roles
        "is_hr": has(settings.ROLE_HR),
        "is_hhc": has(settings.ROLE_HHC),
        "is_cpo": has(settings.ROLE_CPO),
        "is_cao": has(settings.ROLE_CAO),
        "is_cfo": has(settings.ROLE_CFO),
        # workflow capabilities
        "can_prepare": has(*settings.ROLES_PREPARE),
        "can_review": has(*settings.ROLES_REVIEW),
        "can_approve": has(*settings.ROLES_APPROVE),
        "can_disburse": has(*settings.ROLES_DISBURSE),
        "can_reopen": has(*settings.ROLES_REOPEN),
        "can_edit_employees": has(*settings.ROLES_EMPLOYEE_EDIT),
        "can_view_audit": has(*settings.ROLES_AUDIT),
        "can_approve_deductions": has(*settings.ROLES_DEDUCTION_APPROVE),
    }
