from django.http import HttpResponse
from datetime import timedelta, datetime
from ..utils import QueryParams
import functools

import csv, json


def queryset(queryset, request):

    file_name = QueryParams.get_str(request, 'filename') if QueryParams.get_str(request, 'filename') else 'export'

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{file_name}.csv"'

    options = json.loads(request.GET.get('options'))

    order_by = QueryParams.get_str(request, 'order_by')

    writer = csv.writer(response)

    instance = queryset.first()

    keys = None
    values = None

    if options:
        result = get_custom_headers_and_values(queryset, options, order_by=order_by)
        keys = result["keys"]
        values = result["values"]

    header_fields = [f.name for f in instance._meta.fields] if keys is None else keys
    writer.writerow(header_fields)

    dict_values = queryset.values_list() if values is None else values

    for instance in dict_values:
        writer.writerow(instance)

    return response

def get_custom_headers_and_values(queryset, options, order_by=None):

    keys = []
    values = []
    accessor_keys = {}
    formats = {}

    for column in options['columns']:
        keys.append(column["name"])
        accessor_keys[column["name"]] = column['accessor']

        if "type" in column and "format" in column:
            formats[column["name"]] = {"type": column['type'], "format": column["format"]}

    if "select_related" in options and options["select_related"]:
        queryset = queryset.select_related(*options['select_related'],)

    if "prefetch_related" in options and options["prefetch_related"]:
        queryset = queryset.prefetch_related(*options['prefetch_related'],)

    if order_by:
        queryset = queryset.order_by(order_by)

    for instance in queryset:

        temp = []

        for key, accessor_value in accessor_keys.items():
            value = rgetattr(instance, accessor_value)

            if key in formats and value:
                if formats[key]["type"] == "date":
                    value = format_date(value, formats[key]["format"])
                elif formats[key]["type"] == "number":
                    value = format_number(value)

            temp.append(value)

        values.append(temp)

    return {"keys": keys, "values": values}


def rsetattr(obj, attr, val):
    pre, _, post = attr.rpartition('.')
    return setattr(rgetattr(obj, pre) if pre else obj, post, val)


def rgetattr(obj, attr, *args):
    def _getattr(obj, attr):
        if not obj:
            return None
        return getattr(obj, attr, *args)

    if not obj:
        return None
    return functools.reduce(_getattr, [obj] + attr.split('.'))

def format_date(date, format):
    return date.strftime(format)

def format_number(number):
    return "{:,}".format(number)

def verify_list(stats_list, today, min_date):

    if len(stats_list) == 0:
        stats_list.append({
            'date': today,
            "count": 0
        })
        stats_list.append({
            'date': min_date,
            "count": 0
        })

    if stats_list[0]["date"] != today:
        stats_list.insert(0, {
            'date': today,
            "count": 0
        })

    if stats_list[len(stats_list) - 1]["date"] != min_date:
        stats_list.append({
            'date': min_date,
            "count": 0
        })

    return _prepare(stats_list)


def _prepare(array):
    if len(array) > 1:
        array = _sort(array)
        array = _fill(array)

    return array

def _sort(array):
    return sorted(
        array,
        key=lambda x: x['date'], reverse=True
    )


def _fill(array):

    start_date = array[len(array) - 1]['date']
    end_date = array[0]['date']

    days_no = (end_date - start_date).days  # how many days between?

    filled_array = []
    for i in range(days_no + 1):
        date = start_date + timedelta(days=i)
        filled_array.append({
            "date": date,
            "count": 0,
        })

    for i, entry in enumerate(array, start=0):
        for j, data in enumerate(filled_array, start=0):
            if entry["date"] == data["date"]:
                data["count"] = entry["count"]

    return filled_array