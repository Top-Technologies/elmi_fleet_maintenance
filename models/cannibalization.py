from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools.float_utils import float_compare


COST_RULES = [
    ('pending', 'Pending client decision'),
    ('book_value', 'Transfer donor book value'),
    ('zero', 'Transfer at zero'),
    ('standard_price', 'Transfer at product cost'),
]
AGING_BUCKETS = [
    ('0_7', '0-7 days'),
    ('8_30', '8-30 days'),
    ('31_90', '31-90 days'),
    ('90_plus', '90+ days'),
]
ALERT_REASONS = [
    ('open_too_long', 'Open too long'),
    ('transit_too_long', 'In transit too long'),
    ('repeated', 'Repeated cannibalization'),
]


class ElmiCannibalization(models.Model):
    _name = 'elmi.cannibalization'
    _description = 'Cannibalization'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'elmi.security.mixin', 'elmi.stock.transfer.mixin']
    _order = 'id desc'

    _donor_not_recipient = models.Constraint(
        'CHECK(donor_vehicle_id != recipient_vehicle_id)',
        'The donor and the recipient must be different vehicles.',
    )

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    donor_vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    recipient_vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    product_id = fields.Many2one('product.product', required=True, tracking=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial', required=True, tracking=True, domain="[('product_id', '=', product_id)]")
    qty = fields.Float(required=True, default=1.0, tracking=True)
    reason = fields.Text(required=True, tracking=True)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, tracking=True)
    donor_request_id = fields.Many2one('maintenance.request', string='Donor Work Order', tracking=True)
    recipient_request_id = fields.Many2one('maintenance.request', string='Recipient Work Order', tracking=True)
    photo_ids = fields.Many2many('ir.attachment', 'elmi_cannibalization_photo_rel', 'cannibalization_id', 'attachment_id', string='Photos')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('in_transit', 'In Transit'),
            ('installed', 'Installed'),
            ('closed', 'Closed'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    workshop_approved = fields.Boolean(tracking=True, copy=False)
    fleet_approved = fields.Boolean(tracking=True, copy=False)
    picking_out_id = fields.Many2one('stock.picking', string='Transit Transfer', copy=False)
    picking_in_id = fields.Many2one('stock.picking', string='Install Transfer', copy=False)
    transit_start = fields.Datetime(copy=False)
    part_cost = fields.Monetary(currency_field='currency_id', copy=False)
    transferred_cost = fields.Monetary(currency_field='currency_id', copy=False)
    cost_rule = fields.Selection(COST_RULES, default=lambda self: self.env.company.elmi_cost_rule or 'pending', required=True, tracking=True)
    cost_posted = fields.Boolean(copy=False, help='Set by a future accounting module. This module never posts a journal entry.')
    replacement_ids = fields.One2many('elmi.cannibalization.replacement', 'cannibalization_id', string='Replacements')
    alert_reason = fields.Selection(ALERT_REASONS, string='Alert', copy=False)
    alert_reason_detail = fields.Char(string='Alert Detail', copy=False)
    aging_bucket = fields.Selection(AGING_BUCKETS, string='Aging', copy=False)
    open_days = fields.Integer(compute='_compute_open_days')

    @api.depends('create_date', 'state')
    def _compute_open_days(self):
        today = fields.Date.context_today(self)
        for record in self:
            start = fields.Date.to_date(record.create_date) if record.create_date else today
            record.open_days = max((today - start).days, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('elmi.cannibalization') or _('New')
            if not vals.get('cost_rule'):
                vals['cost_rule'] = self.env.company.elmi_cost_rule or 'pending'
            if vals.get('donor_vehicle_id') and vals.get('donor_vehicle_id') == vals.get('recipient_vehicle_id'):
                raise ValidationError(_("The donor and the recipient must be different vehicles."))
        records = super().create(vals_list)
        records._elmi_refresh_aging()
        return records

    @api.constrains('donor_vehicle_id', 'recipient_vehicle_id', 'product_id', 'lot_id', 'qty', 'state')
    def _check_cannibalization(self):
        for record in self:
            if record.donor_vehicle_id and record.donor_vehicle_id == record.recipient_vehicle_id:
                raise ValidationError(_("The donor and the recipient must be different vehicles."))
            product = record.product_id
            if product and product.tracking == 'none':
                raise ValidationError(_("Cannibalized parts must be tracked by lot or serial."))
            if record.lot_id and record.lot_id.product_id != product:
                raise ValidationError(_("The lot does not belong to the selected product."))
            if product and product.tracking == 'serial' and float_compare(record.qty, 1.0, precision_rounding=product.uom_id.rounding) != 0:
                raise ValidationError(_("A serial-tracked part must be transferred with quantity 1."))
            if record.qty <= 0:
                raise ValidationError(_("Quantity must be positive."))
            if record.lot_id and record.state not in ('closed', 'cancelled'):
                duplicate = self.search([
                    ('id', '!=', record.id),
                    ('lot_id', '=', record.lot_id.id),
                    ('state', 'not in', ('closed', 'cancelled')),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Lot %s already has an open cannibalization (%s).",
                        record.lot_id.display_name,
                        duplicate.name,
                    ))

    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_("Only a draft cannibalization can be submitted."))
            if not record.donor_vehicle_id.elmi_fleet_class:
                raise UserError(_("Set the fleet class on the donor vehicle before submitting."))
        self.write({'state': 'submitted'})
        self._elmi_schedule_group_activity(
            'elmi_fleet_maintenance.group_elmi_workshop_head',
            _('Approve cannibalization'),
            _('Workshop approval is required.'),
        )
        return True

    def action_approve_workshop(self):
        self._elmi_check_groups(
            ['elmi_fleet_maintenance.group_elmi_workshop_head'],
            _("Only the Garage Workshop Head can give workshop approval."),
        )
        for record in self:
            if record.state != 'submitted':
                raise UserError(_("Workshop approval is available after the record is submitted."))
        self.write({'workshop_approved': True})
        self._elmi_finalize_approval()
        return True

    def action_approve_fleet(self):
        for record in self:
            if record.state != 'submitted':
                raise UserError(_("Fleet approval is available after the record is submitted."))
            xmlid = record._elmi_fleet_group_xmlid()
            record._elmi_check_groups(
                [xmlid],
                _("Fleet approval must be given by the %(klass)s fleet manager.", klass=record.donor_vehicle_id.elmi_fleet_class),
            )
        self.write({'fleet_approved': True})
        self._elmi_finalize_approval()
        return True

    def _elmi_fleet_group_xmlid(self):
        self.ensure_one()
        if self.donor_vehicle_id.elmi_fleet_class == 'heavy':
            return 'elmi_fleet_maintenance.group_elmi_heavy_fleet_manager'
        if self.donor_vehicle_id.elmi_fleet_class == 'light':
            return 'elmi_fleet_maintenance.group_elmi_light_fleet_manager'
        raise UserError(_("Set the donor vehicle fleet class to Heavy or Light."))

    def _elmi_finalize_approval(self):
        ready = self.filtered(lambda record: record.state == 'submitted' and record.workshop_approved and record.fleet_approved)
        if ready:
            ready.write({'state': 'approved'})
            for record in ready:
                record._elmi_on_approved()

    def _elmi_on_approved(self):
        self.ensure_one()
        self._elmi_apply_cost_rule()
        if not self.replacement_ids:
            self.env['elmi.cannibalization.replacement'].create({
                'cannibalization_id': self.id,
                'donor_vehicle_id': self.donor_vehicle_id.id,
                'product_id': self.product_id.id,
                'qty': self.qty,
                'company_id': self.company_id.id,
            })
        if self.company_id.elmi_auto_replacement_po:
            self.replacement_ids.filtered(lambda replacement: not replacement.purchase_order_id)._elmi_create_draft_purchase_order()
        self._elmi_create_procurement_request()

    def _elmi_apply_cost_rule(self):
        """Cost rule is a placeholder until O-FL-22 is decided. Nothing is posted."""
        for record in self:
            part_cost = (record.product_id.standard_price or 0.0) * (record.qty or 0.0)
            if record.cost_rule in ('standard_price', 'book_value'):
                transferred = part_cost
            else:
                transferred = 0.0
            record.write({
                'part_cost': part_cost,
                'transferred_cost': transferred,
                'cost_posted': False,
            })
        return True

    def elmi_hook_post_cost_transfer(self):
        """Phase 2 accounting hook.

        Override this method to create the journal entry that moves cost from
        the donor to the recipient, then set ``cost_posted``. This module does
        not create accounting entries.
        """
        self.ensure_one()
        return False

    def _elmi_prepare_procurement_request_vals(self):
        """Values for a future Procurement purchase-request document."""
        self.ensure_one()
        return {
            'origin': self.name,
            'product_id': self.product_id.id,
            'qty': self.qty,
            'uom_id': self.product_id.uom_id.id,
            'donor_vehicle_id': self.donor_vehicle_id.id,
            'company_id': self.company_id.id,
            'reason': self.reason,
        }

    def _elmi_create_procurement_request(self):
        """Extension point. Override to create a Procurement purchase request.

        The base module returns False and does not depend on a procurement app.
        Use ``_elmi_prepare_procurement_request_vals`` for the payload.
        """
        return False

    def action_start_transit(self):
        for record in self:
            if record.state != 'approved':
                raise UserError(_("Start transit only after both approvals."))
            transit = record.company_id.elmi_transit_location_id
            if not transit:
                raise UserError(_("Set the cannibalization in-transit location in Fleet Maintenance settings."))
            source = record._elmi_donor_location()
            picking = record._elmi_validate_internal_transfer(
                lines=[{
                    'product': record.product_id,
                    'qty': record.qty,
                    'uom': record.product_id.uom_id,
                    'lot': record.lot_id,
                }],
                location=source,
                location_dest=transit,
                origin=record.name,
                picking_vals={'elmi_cannibalization_id': record.id},
            )
            record.write({
                'state': 'in_transit',
                'picking_out_id': picking.id,
                'transit_start': fields.Datetime.now(),
            })
        return True

    def action_install(self):
        for record in self:
            if record.state != 'in_transit':
                raise UserError(_("Install the part only while it is in transit."))
            transit = record.company_id.elmi_transit_location_id
            destination = record.recipient_vehicle_id.elmi_stock_location_id
            if not destination:
                raise UserError(_("Set a part location on the recipient vehicle."))
            picking = record._elmi_validate_internal_transfer(
                lines=[{
                    'product': record.product_id,
                    'qty': record.qty,
                    'uom': record.product_id.uom_id,
                    'lot': record.lot_id,
                }],
                location=transit,
                location_dest=destination,
                origin=record.name,
                picking_vals={'elmi_cannibalization_id': record.id},
            )
            record.lot_id.elmi_installed_vehicle_id = record.recipient_vehicle_id
            record.write({'state': 'installed', 'picking_in_id': picking.id})
        return True

    def action_close(self):
        for record in self:
            if record.state != 'installed':
                raise UserError(_("Close the cannibalization after the part is installed."))
        self.write({'state': 'closed'})
        return True

    def action_cancel(self):
        for record in self:
            if record.state in ('in_transit', 'installed', 'closed'):
                raise UserError(_("A cannibalization that has already moved stock cannot be cancelled."))
        self.write({'state': 'cancelled'})
        return True

    def action_view_pickings(self):
        self.ensure_one()
        pickings = (self.picking_out_id | self.picking_in_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
        }

    def _elmi_donor_location(self):
        """Part-location rule is open (O-FL-22).

        Use the lot's current internal location, then the donor vehicle location,
        then the configured garage store.
        """
        self.ensure_one()
        lot_location = self.lot_id.location_id
        if lot_location and lot_location.usage == 'internal':
            return lot_location
        if self.donor_vehicle_id.elmi_stock_location_id:
            return self.donor_vehicle_id.elmi_stock_location_id
        garage = self.company_id.elmi_garage_location_id
        if garage:
            return garage
        raise UserError(_("No donor location is available. Set the lot location, the vehicle part location, or the garage store."))

    def _elmi_refresh_aging(self):
        for record in self:
            record.aging_bucket = record._elmi_bucket(record.open_days)

    @api.model
    def _elmi_bucket(self, days):
        if days <= 7:
            return '0_7'
        if days <= 30:
            return '8_30'
        if days <= 90:
            return '31_90'
        return '90_plus'

    @api.model
    def _cron_refresh_alerts(self):
        today = fields.Date.context_today(self)
        records = self.search([('state', 'not in', ('cancelled',))])
        for company in records.mapped('company_id'):
            company_records = records.filtered(lambda record: record.company_id == company)
            for record in company_records:
                reasons = []
                if (
                    company.elmi_max_open_days
                    and record.state in ('draft', 'submitted', 'approved')
                    and record.open_days > company.elmi_max_open_days
                ):
                    reasons.append('open_too_long')
                if company.elmi_max_transit_days and record.state == 'in_transit' and record.transit_start:
                    transit_days = (today - fields.Date.to_date(record.transit_start)).days
                    if transit_days > company.elmi_max_transit_days:
                        reasons.append('transit_too_long')
                if company.elmi_repeat_count and company.elmi_repeat_window_days:
                    window_start = fields.Datetime.now() - relativedelta(days=company.elmi_repeat_window_days)
                    count = self.search_count([
                        ('donor_vehicle_id', '=', record.donor_vehicle_id.id),
                        ('product_id', '=', record.product_id.id),
                        ('state', '!=', 'cancelled'),
                        ('create_date', '>=', window_start),
                    ])
                    if count >= company.elmi_repeat_count:
                        reasons.append('repeated')
                record.write({
                    'alert_reason': reasons[0] if reasons else False,
                    'alert_reason_detail': ', '.join(reasons) if reasons else False,
                    'aging_bucket': record._elmi_bucket(record.open_days),
                })
                if reasons:
                    record._elmi_schedule_group_activity(
                        'elmi_fleet_maintenance.group_elmi_workshop_head',
                        _('Cannibalization alert'),
                        record.alert_reason_detail or _('Review this cannibalization.'),
                    )
        self.env['elmi.cannibalization.replacement'].search([('status', '!=', 'closed')])._elmi_touch_age()


class ElmiCannibalizationReplacement(models.Model):
    _name = 'elmi.cannibalization.replacement'
    _description = 'Cannibalization Replacement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    cannibalization_id = fields.Many2one('elmi.cannibalization', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    donor_vehicle_id = fields.Many2one('fleet.vehicle', required=True, index=True)
    product_id = fields.Many2one('product.product', required=True, index=True)
    qty = fields.Float(required=True, default=1.0)
    status = fields.Selection(
        [
            ('open', 'Open'),
            ('ordered', 'Ordered'),
            ('received', 'Received'),
            ('closed', 'Closed'),
        ],
        default='open',
        required=True,
        tracking=True,
    )
    age_days = fields.Integer(compute='_compute_age_days')
    purchase_order_id = fields.Many2one('purchase.order', copy=False)
    receipt_picking_id = fields.Many2one('stock.picking', string='Receipt', copy=False)
    close_date = fields.Date()

    @api.depends('create_date', 'close_date', 'status')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for replacement in self:
            start = fields.Date.to_date(replacement.create_date) if replacement.create_date else today
            end = replacement.close_date or today
            replacement.age_days = max((end - start).days, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('elmi.cannibalization.replacement') or _('New')
        return super().create(vals_list)

    def _elmi_touch_age(self):
        """Re-read age_days so list views opened after the daily cron show a fresh value."""
        self._compute_age_days()
        self.env['elmi.cannibalization'].search([])._elmi_refresh_aging()

    def _elmi_create_draft_purchase_order(self):
        for replacement in self:
            seller = replacement.product_id.seller_ids[:1]
            if not seller:
                replacement.cannibalization_id.message_post(body=_(
                    "No vendor is set on %s, so no replacement RFQ was created.",
                    replacement.product_id.display_name,
                ))
                continue
            purchase = self.env['purchase.order'].create({
                'partner_id': seller.partner_id.id,
                'origin': replacement.cannibalization_id.name,
                'company_id': replacement.company_id.id,
                'elmi_cannibalization_id': replacement.cannibalization_id.id,
                'elmi_replacement_id': replacement.id,
                'elmi_vehicle_id': replacement.donor_vehicle_id.id,
                'order_line': [Command.create({
                    'product_id': replacement.product_id.id,
                    'product_qty': replacement.qty,
                    'product_uom_id': replacement.product_id.uom_id.id,
                    'price_unit': seller.price or replacement.product_id.standard_price,
                    'date_planned': fields.Datetime.now(),
                    'name': replacement.product_id.display_name,
                })],
            })
            replacement.write({'purchase_order_id': purchase.id, 'status': 'ordered'})

    def action_close(self):
        self.write({'status': 'closed', 'close_date': fields.Date.context_today(self)})
        return True

    def action_mark_received(self):
        self.filtered(lambda replacement: replacement.status != 'closed').write({'status': 'received'})
        return True
