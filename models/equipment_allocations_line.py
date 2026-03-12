from odoo import models, fields, api, exceptions


class EquipmentAllocationsLines(models.Model):
    _name = "equipment.allocations.line"
    _description = "Línea de asignación de equipos"
    _rec_name = "display_name"
    _order = "id DESC"
    _inherit = ["mail.thread"]

    uid = fields.Char("UID", readonly=True, copy=False, index=True, default="Borrador")
    display_name = fields.Char(string="Nombre", compute="_compute_display_name")
    employee_id = fields.Many2one("hr.employee", string="Empleado")

    equipment_id = fields.Many2one(
        "maintenance.equipment", string="Equipo", required=True, ondelete="restrict"
    )
    warehouse_origin_id = fields.Many2one("stock.warehouse", string="Almacén de origen")
    warehouse_dest_id = fields.Many2one("stock.warehouse", string="Almacén de destino")
    quantity = fields.Integer(string="Cantidad")

    is_applied = fields.Boolean(string="Aplicado?", default=False)
    is_canceled = fields.Boolean(string="Cancelado?", default=False)
    origin = fields.Char(string="Origen", default="")

    move_type = fields.Selection(
        [
            ("assigned", "Asignación"),
            ("return", "Devolución"),
            ("income", "Ingreso"),
            ("output", "Salida"),
        ],
        string="Tipo de movimiento",
        default="assigned",
        required=True,
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.uid if rec.uid else 'NA'} / {rec.equipment_id.name}"
            )

    def _get_or_create_warehouse_line(self, equipment, warehouse):
        line = self.env["warehouse.allocations.line"].search(
            [
                ("equipment_id", "=", equipment.id),
                ("warehouse_id", "=", warehouse.id),
            ],
            limit=1,
        )

        if not line:
            line = self.env["warehouse.allocations.line"].create(
                {
                    "equipment_id": equipment.id,
                    "warehouse_id": warehouse.id,
                }
            )

        return line

    def _clean_empty_warehouse_lines(self, equipment):
        self.env["warehouse.allocations.line"].search(
            [
                ("equipment_id", "=", equipment.id),
                ("quantity_total", "=", 0),
                ("quantity_used", "=", 0),
            ]
        ).unlink()

    @api.constrains("quantity")
    def _check_quantity(self):
        for rec in self:
            if rec.quantity < 0:
                raise exceptions.ValidationError("La cantidad debe ser mayor que cero.")

    def _apply_record(self):
        self.write(
            {
                "uid": (
                    self.uid
                    if self.uid != "Borrador"
                    else self.env["ir.sequence"].next_by_code(
                        "equipment.allocations.line"
                    )
                ),
                "is_applied": True,
            }
        )

    def apply_movement(self):
        for rec in self:
            self.env.cr.execute(
                "SELECT id FROM maintenance_equipment WHERE id = %s FOR UPDATE",
                (rec.equipment_id.id,),
            )

            if rec.is_applied:
                raise exceptions.UserError("Este movimiento ya fue aplicado.")

            if rec.quantity <= 0:
                raise exceptions.ValidationError("La cantidad debe ser mayor a 0.")

            if rec.move_type == "assigned":
                if not rec.employee_id:
                    raise exceptions.UserError(
                        "Debe haber un empleado para realizar la operación de asignación."
                    )

                if not rec.warehouse_origin_id:
                    raise exceptions.ValidationError(
                        "Debe seleccionar un almacén de origen."
                    )

                self.env.cr.execute(
                    "SELECT id FROM warehouse_allocations_line WHERE equipment_id=%s AND warehouse_id=%s FOR UPDATE",
                    (rec.equipment_id.id, rec.warehouse_origin_id.id),
                )

                warehouse = self.env["warehouse.allocations.line"].search(
                    [
                        ("equipment_id", "=", rec.equipment_id.id),
                        ("warehouse_id", "=", rec.warehouse_origin_id.id),
                    ],
                    limit=1,
                )

                if not warehouse:
                    raise exceptions.ValidationError(
                        "El equipo no existe en ese almacén."
                    )

                if warehouse.quantity_available < rec.quantity:
                    raise exceptions.ValidationError(
                        "No hay disponibilidad suficiente para esta operación."
                    )

                rec.equipment_id.write(
                    {
                        "employee_ids": [(4, rec.employee_id.id)],
                        "quantity_used": rec.equipment_id.quantity_used + rec.quantity,
                    }
                )
                rec._apply_record()
                continue

            if rec.move_type == "return":
                if not rec.employee_id:
                    raise exceptions.UserError(
                        "Debe haber un empleado para realizar la operación de devolución."
                    )

                if not rec.warehouse_dest_id:
                    raise exceptions.ValidationError(
                        "Debe seleccionar un almacén de destino."
                    )

                self.env.cr.execute(
                    "SELECT id FROM warehouse_allocations_line WHERE equipment_id=%s AND warehouse_id=%s FOR UPDATE",
                    (rec.equipment_id.id, rec.warehouse_dest_id.id),
                )

                domain = [
                    ("equipment_id", "=", rec.equipment_id.id),
                    ("employee_id", "=", rec.employee_id.id),
                    ("is_applied", "=", True),
                    ("move_type", "in", ["assigned", "return"]),
                    ("warehouse_dest_id", "=", rec.warehouse_dest_id.id),
                ]

                grouped = self.read_group(
                    domain,
                    ["move_type", "quantity:sum"],
                    ["move_type"],
                )

                assigned_total = 0
                return_total = 0

                for row in grouped:
                    qty = row.get("quantity") or 0
                    if row.get("move_type") == "assigned":
                        assigned_total = qty
                    elif row.get("move_type") == "return":
                        return_total = qty

                available_to_return = assigned_total - return_total

                if rec.quantity > available_to_return:
                    raise exceptions.ValidationError(
                        f"No puede devolver {rec.quantity}.\n"
                        f"El empleado {rec.employee_id.name} solo tiene {available_to_return} equipo(s) asignado(s)."
                    )

                still_has_equipment = assigned_total - return_total - rec.quantity

                values = {
                    "quantity_used": rec.equipment_id.quantity_used - rec.quantity,
                }

                if still_has_equipment <= 0:
                    values["employee_ids"] = [(3, rec.employee_id.id)]

                rec.equipment_id.write(values)

                rec._apply_record()
                continue

            if rec.move_type == "income":
                if rec.employee_id:
                    raise exceptions.UserError(
                        "No puede haber empleados en un movimiento de ingreso."
                    )

                if not rec.warehouse_dest_id:
                    raise exceptions.ValidationError(
                        "Debe seleccionar un almacén de destino."
                    )

                self.env.cr.execute(
                    "SELECT id FROM warehouse_allocations_line WHERE equipment_id=%s AND warehouse_id=%s FOR UPDATE",
                    (rec.equipment_id.id, rec.warehouse_dest_id.id),
                )

                line = self._get_or_create_warehouse_line(
                    rec.equipment_id, rec.warehouse_dest_id
                )
                line.quantity_total += rec.quantity

                rec.equipment_id.write(
                    {
                        "quantity_total_equipment": rec.equipment_id.quantity_total_equipment
                        + rec.quantity
                    }
                )

                rec._apply_record()

                self._clean_empty_warehouse_lines(rec.equipment_id)
                continue

            if rec.move_type == "output":
                if rec.employee_id:
                    raise exceptions.UserError(
                        "No puede haber empleados en un movimiento de salida."
                    )

                if not rec.warehouse_origin_id:
                    raise exceptions.ValidationError(
                        "Debe seleccionar un almacén de origen."
                    )

                self.env.cr.execute(
                    "SELECT id FROM warehouse_allocations_line WHERE equipment_id=%s AND warehouse_id=%s FOR UPDATE",
                    (rec.equipment_id.id, rec.warehouse_origin_id.id),
                )

                line = self.env["warehouse.allocations.line"].search(
                    [
                        ("equipment_id", "=", rec.equipment_id.id),
                        ("warehouse_id", "=", rec.warehouse_origin_id.id),
                    ],
                    limit=1,
                )

                if not line:
                    raise exceptions.UserError("El equipo no existe en ese almacén.")

                if line.quantity_available < rec.quantity:
                    raise exceptions.ValidationError(
                        "No hay cantidad disponible para realizar la salida."
                    )

                new_qty = line.quantity_total - rec.quantity

                rec.equipment_id.write(
                    {
                        "quantity_total_equipment": rec.equipment_id.quantity_total_equipment
                        - rec.quantity
                    }
                )

                rec._apply_record()

                if new_qty <= 0:
                    line.unlink()
                continue

    def cancel_movements(self):
        for rec in self:
            if not rec.is_applied:
                raise exceptions.ValidationError("El movimiento no ha sido aplicado")

            rec.write({"is_canceled": True})
            if rec.move_type == "assigned":
                rec.create(
                    {
                        "equipment_id": rec.equipment_id.id,
                        "employee_id": rec.employee_id.id,
                        "move_type": "return",
                        "quantity": rec.quantity,
                        "origin": rec.uid,
                        "warehouse_origin_id": rec.warehouse_dest_id.id,
                        "warehouse_dest_id": rec.warehouse_origin_id.id,
                    }
                ).apply_movement()
                continue

            if rec.move_type == "return":
                rec.create(
                    {
                        "equipment_id": rec.equipment_id.id,
                        "employee_id": rec.employee_id.id,
                        "move_type": "assigned",
                        "quantity": rec.quantity,
                        "origin": rec.uid,
                        "warehouse_origin_id": rec.warehouse_dest_id.id,
                        "warehouse_dest_id": rec.warehouse_origin_id.id,
                    }
                ).apply_movement()
                continue

            if rec.move_type == "income":
                rec.create(
                    {
                        "equipment_id": rec.equipment_id.id,
                        "move_type": "output",
                        "quantity": rec.quantity,
                        "origin": rec.uid,
                        "warehouse_origin_id": rec.warehouse_dest_id.id,
                        "warehouse_dest_id": rec.warehouse_origin_id.id,
                    }
                ).apply_movement()
                continue

            if rec.move_type == "output":
                rec.create(
                    {
                        "equipment_id": rec.equipment_id.id,
                        "move_type": "income",
                        "quantity": rec.quantity,
                        "origin": rec.uid,
                        "warehouse_origin_id": rec.warehouse_dest_id.id,
                        "warehouse_dest_id": rec.warehouse_origin_id.id,
                    }
                ).apply_movement()
                continue

    def action_delete(self):
        self.unlink()
        return {
            "type": "ir.actions.act_window",
            "name": "Asignación de equipos",
            "res_model": "equipment.allocations.line",
            "view_mode": "list,form",
            "path": "equipment_allocations",
            "target": "main",
        }

    def unlink(self):
        for rec in self:
            if rec.is_applied:
                raise exceptions.UserError(
                    "No se puede eliminar movimientos aplicados."
                )

        return super(EquipmentAllocationsLines, self).unlink()
