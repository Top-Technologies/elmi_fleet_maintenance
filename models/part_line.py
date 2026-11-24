from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ElmiMaintenancePartLine(models.Model):
    _name = 'elmi.maintenance.part.line'
    _description = 'Maintenance Part Line'
    _inherit = ['elmi.security.mixin', 'elmi.stock.transfer.mixin']
    _order = 'id'

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    request_id = fields.Many2one('maintenance.request', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    product_id = fields.Many2one('product.product', required=True)
    qty = fields.Float(required=True, default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial', domain="[('product_id', '=', product_id)]")
    source_location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        default=lambda self: self._default_source_location(),
        domain="[('usage', '=', 'internal')]",
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('issued', 'Issued'),
            ('returned', 'Returned'),
        ],
        default='draft',
        required=True,
    )
    submitted = fields.Boolean(copy=False)
    picking_id = fields.Many2one('stock.picking', string='Issue Transfer', copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Return Transfer', copy=False)
    cost = fields.Monetary(currency_field='currency_id', copy=False)

    @api.model
    def _default_source_location(self):
        return self.env.company._elmi_part_source_location().id

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('elmi.maintenance.part.line') or _('New')
            if vals.get('product_id') and not vals.get('uom_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                vals['uom_id'] = product.uom_id.id
        return super().create(vals_list)

    def write(self, vals):
        protected = {'product_id', 'qty', 'uom_id', 'lot_id'}
        if protected.intersection(vals):
            locked = self.filtered(lambda line: line.state != 'draft' or line.submitted)
            if locked:
                raise UserError(_("Submitted part lines cannot be edited. Return the part and add a new line."))
        return super().write(vals)

    def action_submit(self):
        for line in self:
            if line.state != 'draft' or line.submitted:
                raise UserError(_("Only a draft line can be submitted."))
            if line.qty <= 0:
                raise UserError(_("Enter a positive quantity."))
        self.write({'submitted': True})
        requests = self.mapped('request_id')
        requests._elmi_schedule_part_approval()
        return True

    def action_approve(self):
        self._elmi_check_groups(
            ['elmi_fleet_maintenance.group_elmi_workshop_head'],
            _("Only the Garage Workshop Head can approve parts."),
        )
        for line in self:
            if line.state != 'draft' or not line.submitted:
                raise UserError(_("Submit the part line before approval."))
        self.write({'state': 'approved'})
        return True

    def action_issue(self):
        self._elmi_check_groups(
            [
                'elmi_fleet_maintenance.group_elmi_storekeeper',
                'elmi_fleet_maintenance.group_elmi_workshop_head',
            ],
            _("Only the Garage Storekeeper can issue parts."),
        )
        for line in self:
            line._elmi_issue_one()
        return True

    def _elmi_issue_one(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Approve the part line before issuing it."))
        company = self.company_id or self.env.company
        source = self.source_location_id or company._elmi_part_source_location()
        destination = company.elmi_consumption_location_id
        if not source or not destination:
            raise UserError(_("Set the garage store and the maintenance consumption location in Fleet Maintenance settings."))
        picking = self._elmi_validate_internal_transfer(
            lines=[{
                'product': self.product_id,
                'qty': self.qty,
                'uom': self.uom_id,
                'lot': self.lot_id,
            }],
            location=source,
            location_dest=destination,
            origin=self.request_id.name,
            picking_vals={'elmi_maintenance_request_id': self.request_id.id},
            move_vals={'elmi_maintenance_request_id': self.request_id.id},
        )
        move = picking.move_ids.filtered(lambda item: item.product_id == self.product_id)[:1]
        self.write({
            'state': 'issued',
            'picking_id': picking.id,
            'cost': self._elmi_move_value(move) if move else self.qty * (self.product_id.standard_price or 0.0),
        })

    def action_return(self):
        self._elmi_check_groups(
            [
                'elmi_fleet_maintenance.group_elmi_storekeeper',
                'elmi_fleet_maintenance.group_elmi_workshop_head',
            ],
            _("Only the Garage Storekeeper can return parts."),
        )
        for line in self:
            if line.state != 'issued' or not line.picking_id:
                raise UserError(_("Only an issued part can be returned."))
            picking = line._elmi_validate_internal_transfer(
                lines=[{
                    'product': line.product_id,
                    'qty': line.qty,
                    'uom': line.uom_id,
                    'lot': line.lot_id,
                }],
                location=line.picking_id.location_dest_id,
                location_dest=line.picking_id.location_id,
                origin=_("Return of %s", line.picking_id.name),
                picking_vals={'elmi_maintenance_request_id': line.request_id.id},
                move_vals={'elmi_maintenance_request_id': line.request_id.id},
            )
            line.write({'state': 'returned', 'return_picking_id': picking.id})
        return True
