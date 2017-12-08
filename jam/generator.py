import logging

from rest_framework.fields import empty
from rest_framework.utils.model_meta import get_field_info
from rest_framework_json_api.relations import ResourceRelatedField

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.module_loading import import_string

from .utils import get_related_name

logger = logging.getLogger(__name__)


class Generator:
    def __init__(self, api_prefix=None, **kwargs):
        self.api_prefix = api_prefix
        self.exclude_serializers = kwargs.get('exclude_serializers', []) or []
        self.exclude_endpoints = (
            kwargs.get('exclude_endpoints', []) +
            getattr(settings, 'JAM_ENDPOINT_EXCLUDE', [])
        ) or []
        self.encoder = DjangoJSONEncoder()

    def generate(self, included_apps=[], **kwargs):
        api, models = self.find_api_and_models(**kwargs)
        processed_models = {}
        valid_models = []
        for cfg in apps.get_app_configs():
            if not included_apps or cfg.name in included_apps:
                for model in cfg.get_models():
                    valid_models.append(model)
        for type_name, info in models.items():
            model = info.pop('model')
            if model not in valid_models:
                continue
            processed_models[type_name] = info
        return {
            'api': api,
            'models': processed_models
        }

    def find_api_and_models(self):
        raise NotImplemented


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
            logger.info(f'Working on endpoint: {name}')
            if name in self.exclude_endpoints:
                continue
            try:
                model = vs.queryset.model
            except:
                continue
            attrs, related = {}, {}
            sc = vs.serializer_class()
            sc_name = type(sc).__name__
            if sc_name in self.exclude_serializers:
                logger.info(f'  Excluding serializer: {sc_name}')
                continue
            logger.info(f'  Have serializer: {sc_name}')
            for field in sc._readable_fields:
                logger.info(f'    Processing field: {field.field_name}')
                self.process_field(field, model, attrs, related)
            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            parts = name.split('/')
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = 'CRUD'
            if single in models:
                raise Exception(f'duplicate endpoints, need to add a name to viewset: {name}')
            models[single] = {
                'plural': name,
                'attributes': attrs,
                'relattionships': related,
                'model': model
            }
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
