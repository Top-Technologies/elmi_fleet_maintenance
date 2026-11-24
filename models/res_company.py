from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    elmi_pm_done_meter_policy = fields.Selection(
        [
            ('actual', 'Actual meter at completion'),
            ('due', 'Due meter value'),
        ],
        string='Preventive Maintenance Done Meter',
        default='actual',
        help='When a meter-based preventive request is completed, last done meter is set from the live meter or from the due value stored on the request.',
    )
    elmi_service_product_id = fields.Many2one(
        'product.product',
        string='Outsourced Service Product',
        domain="[('type', '=', 'service')]",
    )
    elmi_labor_rate = fields.Float(
        string='Default Labor Rate',
        help='Default hourly labor rate copied onto new maintenance requests. Open decision O-FL-11: leave at 0 until the client confirms the rate.',
    )
    elmi_garage_location_id = fields.Many2one(
        'stock.location',
        string='Garage Store Location',
        domain="[('usage', '=', 'internal')]",
    )
    elmi_consumption_location_id = fields.Many2one(
        'stock.location',
        string='Maintenance Consumption Location',
        domain="[('usage', '=', 'inventory')]",
    )
    elmi_default_part_location_id = fields.Many2one(
        'stock.location',
        string='Default Part Source Location',
        domain="[('usage', '=', 'internal')]",
        help='Default source for parts issued to a work order. Falls back to the garage store. The part-location rule is open decision O-FL-22.',
    )
    elmi_transit_location_id = fields.Many2one(
        'stock.location',
        string='Cannibalization In-Transit Location',
        domain="[('usage', 'in', ('internal', 'transit'))]",
    )
    elmi_auto_replacement_po = fields.Boolean(
        string='Draft Purchase Order for Replacement Parts',
        help='When a cannibalization is approved, create a draft purchase order for the donor replacement if the product has a vendor.',
    )
    elmi_cost_rule = fields.Selection(
        [
            ('pending', 'Pending client decision'),
            ('book_value', 'Transfer donor book value'),
            ('zero', 'Transfer at zero'),
            ('standard_price', 'Transfer at product cost'),
        ],
        string='Cannibalization Cost Rule',
        default='pending',
        help='Open decision O-FL-22. Book value currently uses product cost until the client defines the book-value source. No journal entry is posted.',
    )
    elmi_max_open_days = fields.Integer(
        string='Cannibalization Max Open Days',
        help='Alert when a cannibalization stays in draft, submitted or approved longer than this. 0 disables the alert. Open decision O-FL-23.',
    )
    elmi_max_transit_days = fields.Integer(
        string='Cannibalization Max Transit Days',
        help='Alert when a part stays in transit longer than this. 0 disables the alert. Open decision O-FL-23.',
    )
    elmi_repeat_count = fields.Integer(
        string='Repeated Cannibalization Count',
        help='Alert when the same donor and part are cannibalized at least this many times inside the window. 0 disables the alert. Open decision O-FL-23.',
    )
    elmi_repeat_window_days = fields.Integer(
        string='Repeated Cannibalization Window (Days)',
        help='Look-back window for the repeated cannibalization alert. 0 disables the alert. Open decision O-FL-23.',
    )

    def _elmi_part_source_location(self):
        self.ensure_one()
        return self.elmi_default_part_location_id or self.elmi_garage_location_id
