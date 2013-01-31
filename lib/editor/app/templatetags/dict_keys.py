import datetime
from django import template
register = template.Library()

@register.filter(name='dictKeyLookup')
@register.simple_tag
def dictKeyLookup(adict, key):
    # Try to fetch from the dict, and if it's not found return an empty string.
    return adict.get(key, None)

@register.filter
@register.simple_tag
def multi_key(adict, keys=''):
    key_list = keys.split(',')
    result = adict
    for key in key_list:
        if result:
            result = result.get(key)
    return result

@register.filter
@register.simple_tag
def get_keys(adict):
    return adict.keys()


@register.filter
@register.simple_tag
def kv(tuple, index):
    return tuple[int(index)]


@register.tag
def render_format(parser, token):
    try:
        member_string = str(token)
    except ValueError:
        raise template.TemplateSyntaxError("you must pass a dict")
    return MemberNode(member_string)

class MemberNode(template.Node):
    def __init__(self, member_string):
#        print member_string
        self.member_string = member_string
    def render(self, context):
        return self.member_string



class CurrentTimeNode(template.Node):
    def __init__(self, format_string):
        self.format_string = format_string
    def render(self, context):
        return datetime.datetime.now().strftime(self.format_string)

@register.tag
def current_time(parser, token):
    try:
        # split_contents() knows not to split quoted strings.
        tag_name, format_string = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError("%r tag requires a single argument" % token.contents.split()[0])
    if not (format_string[0] == format_string[-1] and format_string[0] in ('"', "'")):
        raise template.TemplateSyntaxError("%r tag's argument should be in quotes" % tag_name)
    return CurrentTimeNode(format_string[1:-1])