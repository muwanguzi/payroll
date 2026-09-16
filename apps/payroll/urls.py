from django.urls import path

from . import deduction_approvals, views

app_name = "payroll"

urlpatterns = [
    path("deductions/approvals/", deduction_approvals.deduction_approval_index, name="deduction_approval_index"),
    path("deductions/approvals/<str:code>/", deduction_approvals.deduction_approval_list, name="deduction_approval_list"),
    path("deductions/<int:pk>/review/", deduction_approvals.deduction_approval_action, name="deduction_approval_action"),
    path("runs/", views.run_list, name="run_list"),
    path("runs/new/", views.run_create, name="run_create"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/edit/", views.run_edit, name="run_edit"),
    path("runs/<int:pk>/delete/", views.run_delete, name="run_delete"),
    path("runs/<int:pk>/calculate/", views.run_calculate, name="run_calculate"),
    path("runs/<int:pk>/review/", views.run_review, name="run_review"),
    path("runs/<int:pk>/approve/", views.run_approve, name="run_approve"),
    path("runs/<int:pk>/reopen/", views.run_reopen, name="run_reopen"),
    path("runs/<int:pk>/disburse/", views.run_disburse, name="run_disburse"),
    path("runs/<int:pk>/bank-file/", views.run_bank_file, name="run_bank_file"),
    path("runs/<int:pk>/paye-return.csv", views.run_paye_return, name="run_paye_return"),
    path("runs/<int:pk>/nssf-return.csv", views.run_nssf_return, name="run_nssf_return"),
    path("runs/<int:pk>/payslips.pdf", views.run_payslips_pdf, name="run_payslips_pdf"),
    path("runs/<int:pk>/payslips/email/", views.run_payslips_email, name="run_payslips_email"),
    path("payslip/<int:pk>/", views.payslip, name="payslip"),
    path("payslip/<int:pk>/pdf/", views.payslip_pdf, name="payslip_pdf"),
    path("payslip/<int:pk>/email/", views.payslip_email, name="payslip_email"),
]
