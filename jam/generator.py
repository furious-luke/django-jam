from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields import NOT_PROVIDED
from django.utils.module_loading import import_string
from rest_framework.fields import empty
from rest_framework.utils.model_meta import get_field_info
from rest_framework_json_api.relations import ResourceRelatedField

from .utils import get_related_name


class Generator:
    def __init__(self, api_prefix=None):
        self.api_prefix = api_prefix
        self.encoder = DjangoJSONEncoder()

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
            attrs[field_name] = self.extract_options(
                [
                    (('verbose_name', 'label'), None),
                    (('read_only', 'readOnly'), False),
                    ('required', False),
                    ('blank', True),
                    ('null', True),
                    ('default', NOT_PROVIDED),
                    (('max_length', 'maxLength'), None),
                    ('choices', [])
                ],
                field
            )
            attrs[field_name]['type'] = 'char'
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
            related[field_name].update(
                self.extract_options(
                    [
                        (('verbose_name', 'label'), None),
                        (('read_only', 'readOnly'), False),
                        ('required', False),
                        ('blank', True),
                        ('null', True),
                        ('default', NOT_PROVIDED),
                        ('choices', [])
                    ],
                    related_info.model_field
                )
            )
        model_name = model.__name__
        if model_name in processed_models:
            raise TypeError(f'duplicate model name found: "{model_name}"')
        processed_models[model_name] = {
            'plural': names[0],
            'attributes': attrs,
            'relationships': related
        }

    def extract_options(self, options, field):
        opts = {}
        for name in options:
            try:
                name, default = name
            except:
                default = None
            try:
                name, transformed = name
            except:
                transformed = name
            if hasattr(field, name):
                val = getattr(field, name)
                if self.has_option(field, val, default):
                    if callable(val):
                        continue

                    # A bit yucky, but for choices we need to coerce it
                    # to a list first in order to handle model_utils.Choices.
                    if name == 'choices':
                        val = [x for x in val]

                    try:
                        self.encoder.encode(val)
                    except:
                        continue
                    opts[transformed] = val
        return opts

    def has_option(self, field, value, default):
        if not isinstance(default, tuple):
            default = (default,)
        for x in default:
            if value == x:
                return False
        return True


class DRFGenerator(Generator):
    def find_api_and_models(self, api_prefix=None, router_module=None):
        """ Find all endpoints for models.

        Skip any endpoints without a model, and warn if we find duplicate endpoints for
        a model. We will need to be able to choose which one to use. Perhaps interactive?
        """
        api = {}
        models = {}
        router = self.get_router(router_module)
        prefix = api_prefix or self.api_prefix or settings.API_PREFIX
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
            attrs, related = {}, {}
            sc = vs.serializer_class()
            for field in sc._readable_fields:
                self.process_field(field, model, attrs, related)
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            cur[name] = 'CRUD'
            if single in models:
                raise Exception(f'need to add a name to viewset: {name}')
            models[single] = {
                'plural': name,
                'attributes': attrs,
                'relattionships': related
            }
            models[model] = [name, single]
        return api, models

    def process_field(self, field, model, attrs, related):
        if field.field_name in ['id']:
            return
        if isinstance(field, ResourceRelatedField):
            self.process_relationship(field, model, related)
        else:
            self.process_attribute(field, attrs)

    def process_attribute(self, field, attrs):
        opt_names = [
            'label',
            ('read_only', False),
            ('required', False),
            ('allow_blank', True),
            ('default', empty),
            'max_length',
            'choices'
        ]
        opts = {}
        for name in opt_names:
            try:
                name, default = name
            except:
                default = None
            if hasattr(field, name):
                val = getattr(field, name)
                if val != default:
                    opts[name] = val
        attrs[field.field_name] = opts

    def process_relationship(self, field, model, related):
        opt_names = [
            'label',
            ('read_only', False),
            ('required', False),
            ('allow_blank', True),
            ('default', empty)
        ]
        opts = {}
        for name in opt_names:
            try:
                name, default = name
            except:
                default = None
            if hasattr(field, name):
                val = getattr(field, name)
                if val != default:
                    opts[name] = val
        fi = get_field_info(model)
        for field_name, related_info in fi.forward_relations.items():
            if field_name != field.field_name:
                continue
            break
        opts['type'] = related_info.related_model.__name__
        related_name = get_related_name(
            related_info.related_model,
            related_info.model_field
        )
        if related_name:
            opts['relatedName'] = related_name
        if related_info.to_many:
            related['many'] = True
        related[field.field_name] = opts

    def get_router(self, module_path):
        module_path = module_path or settings.ROOT_ROUTERCONF
        if not module_path:
            raise ValueError('invalid router module path')
        return import_string(module_path)
