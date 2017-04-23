from django.apps import apps
from django.utils.module_loading import import_string
from django.db.models.fields import NOT_PROVIDED
from django.conf import settings
from rest_framework.utils.model_meta import get_field_info

from .utils import get_related_name


class Generator:
    def generate(self, included_apps=[], **kwargs):
        api, models = self.find_api_and_models(**kwargs)
        processed_models = {}
        for cfg in apps.get_app_configs():
            if not included_apps or cfg.name in included_apps:
                self.process_app(cfg, models, processed_models)
        return {
            'api': api,
            'models': processed_models
        }

    def find_api_and_models(self):
        raise NotImplemented

    def process_app(self, app, models, processed_models):
        for model in app.get_models():
            if model not in models:
                continue
            self.process_model(app, model, models[model], processed_models)

    def process_model(self, app, model, names, processed_models):
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
        if model_name in processed_models:
            raise TypeError(f'duplicate model name found: "{model_name}"')
        processed_models[model_name] = {
            'attributes': attrs,
            'relationships': related,
            'api': {
                'plural': names[0],
                'single': names[1]
            }
        }


class DRFGenerator(Generator):
    def find_api_and_models(self, api_prefix=None, router_module=None):
        """ Find all endpoints for models.

        Skip any endpoints without a model, and warn if we find duplicate endpoints for
        a model. We will need to be able to choose which one to use. Perhaps interactive?
        """
        api = {}
        models = {}
        router = self.get_router(router_module)
        prefix = api_prefix or settings.API_PREFIX
        if not prefix:
            raise ValueError('invalid API prefix')
        if prefix[0] == '/':
            prefix = prefix[1:]
        if prefix[-1] == '/':
            prefix = prefix[:-1]
        for name, vs, single in router.registry:
            if name in getattr(settings, 'JAM_ENDPOINT_EXCLUDE', []):
                continue
            try:
                model = vs.queryset.model
            except:
                continue
            if model in models:
                raise TypeError(f'duplicate endpoints for model "{model.__name__}" and endpoint "{name}"')
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            cur[name] = 'CRUD'
            models[model] = (name, single)
        return api, models

    def get_router(self, module_path):
        module_path = module_path or settings.ROOT_ROUTERCONF
        if not module_path:
            raise ValueError('invalid router module path')
        return import_string(module_path + '.router')
