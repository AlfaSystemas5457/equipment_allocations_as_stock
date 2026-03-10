from odoo import models, fields, api


class Area(models.Model):
    _name = "equipment.area"
    _description = "Area"

    name = fields.Char("Nombre del area")
