from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    elmi_pm_done_meter_policy = fields.Selection(related='company_id.elmi_pm_done_meter_policy', readonly=False)
    elmi_service_product_id = fields.Many2one(related='company_id.elmi_service_product_id', readonly=False)
    elmi_labor_rate = fields.Float(related='company_id.elmi_labor_rate', readonly=False)
    elmi_garage_location_id = fields.Many2one(related='company_id.elmi_garage_location_id', readonly=False)
    elmi_consumption_location_id = fields.Many2one(related='company_id.elmi_consumption_location_id', readonly=False)
    elmi_default_part_location_id = fields.Many2one(related='company_id.elmi_default_part_location_id', readonly=False)
    elmi_transit_location_id = fields.Many2one(related='company_id.elmi_transit_location_id', readonly=False)
    elmi_auto_replacement_po = fields.Boolean(related='company_id.elmi_auto_replacement_po', readonly=False)
    elmi_cost_rule = fields.Selection(related='company_id.elmi_cost_rule', readonly=False)
    elmi_max_open_days = fields.Integer(related='company_id.elmi_max_open_days', readonly=False)
    elmi_max_transit_days = fields.Integer(related='company_id.elmi_max_transit_days', readonly=False)
    elmi_repeat_count = fields.Integer(related='company_id.elmi_repeat_count', readonly=False)
    elmi_repeat_window_days = fields.Integer(related='company_id.elmi_repeat_window_days', readonly=False)
