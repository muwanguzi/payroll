from django import forms

from .models import PayRun


class _DateInput(forms.DateInput):
    input_type = "date"


class PayRunEditForm(forms.ModelForm):
    class Meta:
        model = PayRun
        fields = ["pay_date", "notes"]
        widgets = {"pay_date": _DateInput(), "notes": forms.Textarea(attrs={"rows": 3})}
