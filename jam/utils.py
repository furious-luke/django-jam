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
