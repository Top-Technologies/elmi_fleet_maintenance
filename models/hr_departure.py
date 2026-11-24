from odoo import models


class HrDepartureWizard(models.TransientModel):
    _inherit = 'hr.departure.wizard'

    def action_register_departure(self):
        """Departure registration is the wizard action. Archive is the button that opens it."""
        self.employee_ids._elmi_guard_tool_clearance()
        return super(HrDepartureWizard, self.with_context(elmi_tool_clearance_checked=True)).action_register_departure()
