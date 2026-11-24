from odoo import api, fields, models


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    elmi_vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', index=True, tracking=True)
    elmi_is_tool = fields.Boolean(string='Is a Tool', tracking=True)
    elmi_signout_ids = fields.One2many('elmi.tool.signout', 'tool_id', string='Sign-outs')
    elmi_current_holder_id = fields.Many2one(
        'hr.employee',
        string='Current Holder',
        compute='_compute_elmi_current_holder_id',
        store=True,
    )

    @api.depends('elmi_signout_ids.state', 'elmi_signout_ids.employee_id')
    def _compute_elmi_current_holder_id(self):
        for equipment in self:
            open_signout = equipment.elmi_signout_ids.filtered(
                lambda signout: signout.state in ('out', 'overdue')
            )[:1]
            equipment.elmi_current_holder_id = open_signout.employee_id
