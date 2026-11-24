from odoo import fields, models, _


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    elmi_maintenance_request_id = fields.Many2one('maintenance.request', string='Maintenance Request', index=True, copy=False)
    elmi_vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', index=True, copy=False)
    elmi_cannibalization_id = fields.Many2one('elmi.cannibalization', string='Cannibalization', index=True, copy=False)
    elmi_replacement_id = fields.Many2one('elmi.cannibalization.replacement', string='Replacement', index=True, copy=False)

    def action_elmi_open_maintenance_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Request'),
            'res_model': 'maintenance.request',
            'view_mode': 'form',
            'res_id': self.elmi_maintenance_request_id.id,
        }
