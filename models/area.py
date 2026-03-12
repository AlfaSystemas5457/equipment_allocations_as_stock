from odoo import models, fields, api


class Area(models.Model):
    _name = "equipment.area"
    _description = "Área de equipos"

    name = fields.Char("Nombre del área")
