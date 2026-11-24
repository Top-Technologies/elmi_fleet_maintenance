from odoo import fields, models, _


class StockLot(models.Model):
    _inherit = 'stock.lot'

    elmi_installed_vehicle_id = fields.Many2one('fleet.vehicle', string='Installed On', index=True, tracking=True)
    elmi_cannibalization_ids = fields.One2many('elmi.cannibalization', 'lot_id', string='Cannibalization')
    elmi_cannibalization_count = fields.Integer(compute='_compute_elmi_cannibalization_count')

    def _compute_elmi_cannibalization_count(self):
        for lot in self:
            lot.elmi_cannibalization_count = len(lot.elmi_cannibalization_ids)

    def action_elmi_open_cannibalization(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cannibalization'),
            'res_model': 'elmi.cannibalization',
            'view_mode': 'list,form',
            'domain': [('lot_id', '=', self.id)],
            'context': {'default_lot_id': self.id, 'default_product_id': self.product_id.id},
        }
