from django.shortcuts import render

from .generator import DRFGenerator
from .exporter import JAMExporter, TinyAPIExporter


class SchemaViewMixin:
    def get_jsdata(self, **data):
        # TODO: Use caching to prevent recalculation every time: it won't
        # change unless the server is redeployed.
        schema = DRFGenerator().generate()
        data['api'] = TinyAPIExporter().export(schema)
        data['models'] = JAMExporter().export(schema)
        return super().get_jsdata(**data)
