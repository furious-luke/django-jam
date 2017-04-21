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
        parser.add_argument('apps', metavar='APPS', nargs='*', help='apps to dump')
        parser.add_argument('--api-output', '-o', default='.', help='output prefix')
        parser.add_argument('--model-output', '-n', default='.', help='output prefix')
        parser.add_argument('--api-prefix', '-a', default='/api/v1', help='API prefix')
        parser.add_argument('--api-router', '-r', help='router module path')

    def handle(self, **options):
        api, models = self.find_api_and_models(options)
        self.dump_models(models, options)
        self.dump_api(api, options)

    def find_api_and_models(self, options):
        """ Find all endpoints for models.

        Skip any endpoints without a model, and warn if we find duplicate endpoints for
        a model. We will need to be able to choose which one to use. Perhaps interactive?
        """
        api = {}
        models = {}
        router = self.get_router(options['api_router'])
        prefix = options['api_prefix']
        if prefix[0] == '/':
            prefix = prefix[1:]
        if prefix[-1] == '/':
            prefix = prefix[:-1]
        for name, vs, single in router.registry:
            try:
                model = vs.queryset.model
            except:
                continue
            if model in models:
                self.stderr.write(f'WARNING: duplicate endpoints for model "{model.__name__}" and endpoint "{name}"')
                continue
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            cur[name] = 'CRUD'
            models[model] = (name, single)
        return api, models

    def dump_models(self, models, options):
        self.models = {}
        for cfg in apps.get_app_configs():
            if not options['apps'] or cfg.name in options['apps']:
                self.process_app(cfg, models)
        fn = os.path.join(options['model_output'], 'models.json')
        self.export(self.models, fn)

    def process_app(self, app, models):
        for model in app.get_models():
            if model not in models:
                continue
            self.process_model(app, model, models[model])

    def process_model(self, app, model, names):
        fi = get_field_info(model)
        attrs, related = {}, {}
        for field_name, field in fi.fields.items():
            attrs[field_name] = {}
            # Use the default if it's provided and not a callable.
            if field.default != NOT_PROVIDED and not callable(field.default):
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
        if model_name in self.models:
            new_name = f'{app.capitalize()}{model_name}'
            self.stderr.write(f'duplicate model name, "{model_name}", using "{new_name}" instead')
            model_name = new_name
        self.models[model_name] = {
            'attributes': attrs,
            'relationships': related,
            'api': {
                'plural': names[0],
                'single': names[1]
            }
        }

    def export(self, data, filename):
        out = json.dumps(data, indent=2, sort_keys=True)
        if filename:
            with open(filename, 'w') as outf:
                outf.write(out)
        else:
            self.stdout.write(out)

    def dump_api(self, api, options):
        fn = os.path.join(options['api_output'], 'api.json')
        self.export(api, fn)

    def get_api(self, options):
        api = {}
        models = {}
        router = self.get_router(options['api_router'])
        prefix = options['api_prefix']
        if prefix[0] == '/':
            prefix = prefix[1:]
        if prefix[-1] == '/':
            prefix = prefix[:-1]
        for name, vs, single in router.registry:
            try:
                model = vs.queryset.model
            except:
                continue
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            cur[name] = 'CRUD'
            models[model] = (name, single)
        return api, models

    def get_router(self, path):
        if not path:
            raise ValueError('invalid router path')
        return import_string(path)
