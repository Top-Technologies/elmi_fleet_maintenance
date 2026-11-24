from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    elmi_maintenance_request_id = fields.Many2one('maintenance.request', string='Maintenance Request', index=True, copy=False)
    elmi_cannibalization_id = fields.Many2one('elmi.cannibalization', string='Cannibalization', index=True, copy=False)

    def _action_done(self):
        result = super()._action_done()
        replacements = self.env['elmi.cannibalization.replacement'].search([
            ('receipt_picking_id', 'in', self.ids),
            ('status', '!=', 'closed'),
        ])
        if replacements:
            replacements.write({
                'status': 'closed',
                'close_date': fields.Date.context_today(self),
            })
        return result


class StockMove(models.Model):
    _inherit = 'stock.move'

    elmi_maintenance_request_id = fields.Many2one('maintenance.request', string='Maintenance Request', index=True, copy=False)
