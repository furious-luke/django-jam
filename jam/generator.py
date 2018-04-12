import logging

import inflection
from rest_framework_json_api.metadata import JSONAPIMetadata

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields import related
from django.utils.module_loading import import_string

from .utils import get_related_name

logger = logging.getLogger(__name__)


class Generator:
    def __init__(self, api_prefix=None, **kwargs):
        self.api_prefix = api_prefix
        self.exclude_serializers = kwargs.get('exclude_serializers', []) or []
        self.exclude_endpoints = (
            (kwargs.get('exclude_endpoints', []) or []) +
            (getattr(settings, 'JAM_ENDPOINT_EXCLUDE', []) or [])
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
            info.pop('serializer_class')
            processed_models[type_name] = info
        return {
            'api': api,
            'models': processed_models
        }

    def find_api_and_models(self):
        raise NotImplemented


class SerializerMetadata(JSONAPIMetadata):
    """ Generate JAM specialised metadata for serializers.

    JAM is very similar to JSONAPIMetadata, but requires a few changes:
      * Ignores all reverse relationships.
      * Includes "relatedName" in forward relationships.
      * M2M fields include a "many=true" value.
      * Ignores "allows_include".
      * Camelcases all option names.
      * Splits results into attributes and relationships.
    """
    try:
        reverse_relations = {
            related.ReverseManyToOneDescriptor,
            related.ReverseOneToOneDescriptor
        }
    except AttributeError:
        reverse_relations = {
            related.ReverseManyRelatedObjectsDescriptor,
            related.ReverseSingleRelatedObjectDescriptor
        }

    def get_serializer_info(self, serializer):
        info = super().get_serializer_info(serializer)
        attributes = {}
        relationships = {}
        for name, field in info.items():
            # Don't worry about ID.
            if name == 'id':
                continue
            destination = attributes
            new_field = {}
            for attr_name, attr_value in field.items():
                if attr_name == 'relationship_type':
                    destination = relationships
                    if attr_value == 'ManyToMany':
                        new_field['many'] = True
                elif attr_name == 'relationship_resource':
                    new_field['type'] = attr_value
                elif attr_name in {'allows_include'}:
                    pass
                else:
                    new_field[inflection.camelize(attr_name, False)] = attr_value
            if new_field.get('reverse'):
                continue
            if new_field['type'] == 'GenericField':
                del new_field['type']
            destination[name] = new_field
        return {
            'attributes': attributes,
            'relationships': relationships
        }

    def get_field_info(self, field, field_name):
        field_info = super().get_field_info(field, field_name)
        serializer = field.parent
        try:
            serializer_model = getattr(serializer.Meta, 'model')
            rel = getattr(serializer_model, field.field_name)
            try:
                rel_type = rel.__class__
            except AttributeError:
                pass
            if rel_type in self.reverse_relations:
                field_info['reverse'] = True
            elif rel_type in self.relation_type_lookup.mapping:
                rel_model = rel.field.target_field.model
                rel_name = get_related_name(rel_model, rel.field)
                if rel_name:
                    field_info['relatedName'] = rel_name
        except KeyError:
            pass
        except AttributeError:
            pass

        # Fields from `SerializerRelationshipMethodField` don't really store
        # whether they're ManyToMany or not. It seems, however, that they will
        # have a member on the field called `child_relation`, which we can use
        # to know if it's a many or not.
        if 'relationship_type' not in field_info and getattr(field, 'child_relation', None):
            field_info['relationship_type'] = 'ManyToMany'

            # We also need to define a relationship resource.
            # TODO: Currently just using the model name, but this should really
            #   be a serializer.
            field_info['relationship_resource'] = field._kwargs['model'].__name__

        return field_info


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
            except Exception:
                continue
            sc_class = vs.serializer_class
            sc_name = sc_class.__name__
            sc = sc_class()
            if sc_name in self.exclude_serializers:
                logger.info(f'  Excluding serializer: {sc_name}')
                continue
            logger.info(f'  Have serializer: {sc_name}')
            meta = SerializerMetadata().get_serializer_info(sc)

            cur = api
            for part in prefix.split('/'):
                cur = cur.setdefault(part, {})
            parts = name.split('/')
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = 'CRUD'
            try:
                # TODO: Get the resource name using JSON-API calls maybe?
                res_name = sc.Meta.resource_name
            except Exception:
                res_name = model.__name__
            if res_name in models:
                if models[res_name]['serializer_class'] != sc_class:
                    raise Exception(f'duplicate endpoints, need to add a resource name for: {name}')
                logger.warning(f'Two endpoints share the same resource name and serializer: {res_name}')
            logger.info(f'  Resource name: {res_name}')
            models[res_name] = {
                'plural': name,
                'attributes': meta['attributes'],
                'relationships': meta['relationships'],
                'model': model,
                'serializer_class': sc_class
            }
        return api, models

    def get_router(self, module_path):
        module_path = module_path or settings.ROOT_ROUTERCONF
        if not module_path:
            raise ValueError('invalid router module path')
        return import_string(module_path)
