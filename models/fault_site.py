from odoo import api, fields, models, _


class ElmiFaultCategory(models.Model):
    _name = 'elmi.fault.category'
    _description = 'Fault Category'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('elmi.fault.category') or _('New')
        return super().create(vals_list)


class ElmiSite(models.Model):
    _name = 'elmi.site'
    _description = 'Site'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('elmi.site') or _('New')
        return super().create(vals_list)
