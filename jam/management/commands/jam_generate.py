import os
import json

from django.core.management.base import BaseCommand
from django.apps import apps
from django.db.models.fields import NOT_PROVIDED
from django.utils.module_loading import import_string
from rest_framework.utils.model_meta import get_field_info


def get_related_name(model, field):
    """ Extract the related name for a field.

    `model` is the model on which the related field exists. `field` is
    the field from the original model.
    """
    opts = model._meta.concrete_model._meta
    all_related_objects = [r for r in opts.related_objects]
    for relation in all_related_objects:
        if relation.field == field:
            if relation.related_name == '+':
                return None
            else:
                return relation.related_name
    return None


class Command(BaseCommand):
    help = 'Generate redux-jam model descriptions.'

    def add_arguments(self, parser):
        parser.add_argument('apps', metavar='A', nargs='+', help='apps to dump')
        parser.add_argument('--api-output', '-o', default='../frontend/api', help='output prefix')
        parser.add_argument('--model-output', '-n', default='../frontend/models', help='output prefix')
        parser.add_argument('--api-prefix', '-a', default='/api/v1', help='API prefix')
        parser.add_argument('--api-router', '-r', help='router module path')

    def handle(self, **options):
        self.dump_models(options)
        self.dump_api(options)

    def dump_models(self, options):
        self.models = {}
        for cfg in apps.get_app_configs():
            if cfg.name in options['apps']:
                self.process_app(cfg)
        fn = os.path.join(options['model_output'], 'models.json')
        self.export(self.models, fn)

    def process_app(self, app):
        for model in app.get_models():
            self.process_model(app, model)

    def process_model(self, app, model):
        fi = get_field_info(model)
        attrs, related = {}, {}
        for field_name, field in fi.fields.items():
            attrs[field_name] = {}
            if field.default != NOT_PROVIDED:
                attrs[field_name]['default'] = field.default
        for field_name, related_info in fi.forward_relations.items():
            related[field_name] = {
                'type': related_info.related_model.__name__,
            }
            related_name = get_related_name(
                related_info.related_model,
                related_info.model_field
            )
            if related_name:
                related[field_name]['relatedName'] = related_name
            if related_info.to_many:
                related[field_name]['many'] = True
        model_name = model.__name__
        self.models[model_name] = {
            'attributes': attrs,
            'relationships': related
        }

    def export(self, data, filename):
        out = json.dumps(data, indent=2, sort_keys=True)
        if filename:
            with open(filename, 'w') as outf:
                outf.write(out)
        else:
            self.stdout.write(out)

    def dump_api(self, options):
        api = self.get_api(options)
        fn = os.path.join(options['api_output'], 'api.json')
        self.export(api, fn)

    def get_api(self, options):
        api = {}
        router = self.get_router(options['api_router'])
        prefix = options['api_prefix']
        if prefix[0] == '/':
            prefix = prefix[1:]
        if prefix[-1] == '/':
            prefix = prefix[:-1]
        for name, vs, single in router.registry:
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            cur[name] = 'CRUD'
        return api

    def get_router(self, path):
        return import_string(path)
