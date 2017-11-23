import json
import os

from jam.exporter import JAMExporter, TinyAPIExporter
from jam.generator import DRFGenerator

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder


class Command(BaseCommand):
    help = 'Generate redux-jam model descriptions.'

    def add_arguments(self, parser):
        parser.add_argument('apps', metavar='APPS', nargs='*', help='apps to dump')
        parser.add_argument('--api-output', '-o', default='.', help='output prefix')
        parser.add_argument('--model-output', '-n', default='.', help='output prefix')
        parser.add_argument('--api-prefix', '-a', help='API prefix')
        parser.add_argument('--api-router', '-r', help='router module path')

    def handle(self, **options):
        schema = DRFGenerator(options['api_prefix']).generate()
        api = TinyAPIExporter().export(schema),
        models = JAMExporter().export(schema)
        self.dump_api(api, options)
        self.dump_models(models, options)

    def dump_models(self, models, options):
        fn = os.path.join(options['model_output'], 'models.json')
        self.export(models, fn)

    def dump_api(self, api, options):
        fn = os.path.join(options['api_output'], 'api.json')
        self.export(api, fn)

    def export(self, data, filename):
        out = json.dumps(data, indent=2, sort_keys=True, cls=DjangoJSONEncoder)
        if filename:
            with open(filename, 'w') as outf:
                outf.write(out)
        else:
            self.stdout.write(out)
