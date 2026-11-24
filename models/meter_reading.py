from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class ElmiMeterReading(models.Model):
    _name = 'elmi.meter.reading'
    _description = 'Meter Reading'
    _order = 'date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True, index=True)
    meter_type = fields.Selection(
        [
            ('odometer_km', 'Odometer (km)'),
            ('engine_hours', 'Engine Hours'),
        ],
        required=True,
        default='odometer_km',
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    value = fields.Float(required=True)
    previous_value = fields.Float(compute='_compute_previous_and_delta', store=True)
    delta = fields.Float(compute='_compute_previous_and_delta', store=True)
    source = fields.Selection(
        [
            ('manual', 'Manual'),
            ('import', 'Import'),
            ('trip_log', 'Trip Log'),
        ],
        default='manual',
        required=True,
        help='trip_log is an import source key only. This module does not read a logistics trip log.',
    )
    meter_replaced = fields.Boolean(string='Meter Replaced')
    meter_replaced_reason = fields.Char(string='Replacement Reason')

    @api.depends('vehicle_id', 'meter_type', 'date', 'value')
    def _compute_previous_and_delta(self):
        for reading in self:
            previous = reading._elmi_previous_reading()
            reading.previous_value = previous.value if previous else 0.0
            reading.delta = (reading.value or 0.0) - reading.previous_value

    def _elmi_previous_reading(self):
        self.ensure_one()
        if not self.vehicle_id or not self.meter_type:
            return self.browse()
        reading_id = self.id if isinstance(self.id, int) else 0
        candidates = self.search([
            ('vehicle_id', '=', self.vehicle_id.id),
            ('meter_type', '=', self.meter_type),
            ('id', '!=', reading_id or 0),
        ])
        if reading_id:
            candidates = candidates.filtered(lambda candidate: candidate.id != reading_id)
        date_value = self.date or fields.Date.context_today(self)
        earlier = candidates.filtered(
            lambda candidate: candidate.date < date_value or (candidate.date == date_value and candidate.id < (reading_id or 0))
        )
        if not earlier:
            return self.browse()
        return earlier.sorted(key=lambda candidate: (candidate.date, candidate.id))[-1]

    @api.constrains('value', 'previous_value', 'meter_replaced', 'meter_replaced_reason', 'meter_type', 'vehicle_id')
    def _check_meter_monotonic(self):
        for reading in self:
            if reading.meter_replaced and not reading.meter_replaced_reason:
                raise ValidationError(_("Enter a reason when the meter has been replaced."))
            if reading.meter_replaced:
                continue
            if float_compare(reading.value, reading.previous_value, precision_digits=2) < 0:
                raise ValidationError(_(
                    "Reading %(value)s is lower than the previous %(previous)s on %(vehicle)s. "
                    "Tick meter replaced and enter a reason to accept a reset.",
                    value=reading.value,
                    previous=reading.previous_value,
                    vehicle=reading.vehicle_id.display_name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        readings = self.browse()
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('elmi.meter.reading') or _('New')
            reading = super().create([vals])
            reading._compute_previous_and_delta()
            readings |= reading
        readings._check_meter_monotonic()
        readings._elmi_sync_odometer()
        readings._elmi_trigger_pm()
        return readings

    def _elmi_sync_odometer(self):
        """Keep fleet.vehicle.odometer in step for kilometre readings.

        The native odometer is the maximum logged value, not the latest date.
        A replacement that resets the meter below that maximum is not copied,
        because inserting it would leave the vehicle showing the old higher figure.
        """
        odometer_model = self.env['fleet.vehicle.odometer']
        for reading in self.filtered(lambda item: item.meter_type == 'odometer_km'):
            vehicle = reading.vehicle_id
            if float_compare(reading.value, vehicle.odometer, precision_digits=2) < 0:
                vehicle.message_post(body=_(
                    "Meter reading %s was not copied to the fleet odometer because it is below the current odometer.",
                    reading.name,
                ))
                continue
            odometer_model.create({
                'vehicle_id': vehicle.id,
                'value': reading.value,
                'date': reading.date,
                'driver_id': vehicle.driver_id.id,
            })
            # The native odometer compute has no dependencies, so drop the cached value.
            vehicle.invalidate_recordset(['odometer'])

    def _elmi_trigger_pm(self):
        plan_model = self.env['elmi.pm.plan.line']
        for reading in self:
            plans = plan_model.search([
                ('vehicle_id', '=', reading.vehicle_id.id),
                ('meter_type', '=', reading.meter_type),
                ('active', '=', True),
            ])
            for plan in plans:
                plan._elmi_trigger_if_due(reading.value)
