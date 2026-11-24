from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools.float_utils import float_compare


class ElmiStockTransferMixin(models.AbstractModel):
    _name = 'elmi.stock.transfer.mixin'
    _description = 'Internal transfer helper for garage stock moves'

    @api.model
    def _elmi_internal_picking_type(self, company):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        if not warehouse or not warehouse.int_type_id:
            raise UserError(_("Configure an internal transfer operation for company %s.", company.display_name))
        return warehouse.int_type_id

    @api.model
    def _elmi_validate_internal_transfer(self, lines, location, location_dest, origin, picking_vals=None, move_vals=None):
        """Create, reserve and validate an internal transfer.

        ``lines`` is a list of dicts: product, qty, uom, and optional lot.
        Raises UserError when the source cannot cover the full quantity.
        """
        if not lines:
            raise UserError(_("Add at least one product before creating a transfer."))
        if not location or not location_dest:
            raise UserError(_("Set both the source and destination locations in Fleet Maintenance settings."))
        if location == location_dest:
            raise UserError(_("The source and destination locations must be different."))

        company = location.company_id or location_dest.company_id or self.env.company
        picking_type = self._elmi_internal_picking_type(company)
        move_commands = []
        for line in lines:
            product = line['product']
            vals = {
                'product_id': product.id,
                'product_uom_qty': line['qty'],
                'product_uom': line['uom'].id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
                'company_id': company.id,
            }
            if move_vals:
                vals.update(move_vals)
            move_commands.append(Command.create(vals))

        picking_values = {
            'picking_type_id': picking_type.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'origin': origin,
            'company_id': company.id,
            'move_ids': move_commands,
        }
        if picking_vals:
            picking_values.update(picking_vals)
        picking = self.env['stock.picking'].create(picking_values)
        picking.action_confirm()
        picking.action_assign()

        remaining = picking.move_ids
        for line in lines:
            move = remaining.filtered(lambda candidate: candidate.product_id == line['product'])[:1]
            remaining -= move
            lot = line.get('lot')
            if not move:
                continue
            if lot and move.move_line_ids:
                move.move_line_ids.write({'lot_id': lot.id})
            elif lot:
                move.lot_ids = [Command.set(lot.ids)]
            if move.state != 'assigned' and move.location_id.should_bypass_reservation():
                self._elmi_force_bypass_line(move, line)

        short = picking.move_ids.filtered(
            lambda move: move.state != 'assigned' or float_compare(
                move.quantity, move.product_uom_qty, precision_rounding=move.product_uom.rounding,
            ) < 0
        )
        if short:
            details = []
            for move in short:
                details.append(_(
                    "%(product)s (need %(need)s %(uom)s, reserved %(reserved)s)",
                    product=move.product_id.display_name,
                    need=move.product_uom_qty,
                    uom=move.product_uom.name,
                    reserved=move.quantity,
                ))
            detail_text = ', '.join(details)
            if picking.state != 'cancel':
                picking.action_cancel()
            raise UserError(_(
                "Not enough stock at %(location)s to complete this transfer: %(details)s",
                location=location.display_name,
                details=detail_text,
            ))

        picking.move_ids.picked = True
        picking.with_context(cancel_backorder=True)._action_done()
        if any(move.state != 'done' for move in picking.move_ids):
            raise UserError(_("Transfer %s could not be completed.", picking.display_name))
        return picking

    @api.model
    def _elmi_force_bypass_line(self, move, line):
        """Inventory and supplier locations do not keep a stock balance to reserve."""
        lot = line.get('lot')
        if move.move_line_ids:
            move.move_line_ids.write({
                'quantity': line['qty'],
                'lot_id': lot.id if lot else False,
                'picked': True,
            })
            return
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': move.picking_id.id,
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
            'quantity': line['qty'],
            'lot_id': lot.id if lot else False,
            'picked': True,
            'company_id': move.company_id.id,
        })

    @api.model
    def _elmi_move_value(self, move):
        """Real move value when price_unit was set, otherwise product cost."""
        quantity = move.quantity or move.product_uom_qty
        unit = move.price_unit or move.product_id.standard_price or 0.0
        return quantity * unit
