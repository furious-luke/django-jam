import json


class JSONExporter:
    def export(self, data, filename):
        out = json.dumps(data, indent=2, sort_keys=True)
        if filename:
            with open(filename, 'w') as outf:
                outf.write(out)
        else:
            self.stdout.write(out)


class JAMExporter(JSONExporter):
    def export(self, schema, output_dir=None):
        models = schema['models']
        if output_dir is not None:
            fn = os.path.join(option_dir, 'models.json')
            super().export(models, fn)
        else:
            return models


class TinyAPIExporter(JSONExporter):
    def export(self, schema, output_dir=None):
        api = schema['api']
        if output_dir is not None:
            fn = os.path.join(output_dir, 'api.json')
            super().export(api, fn)
        else:
            return api
