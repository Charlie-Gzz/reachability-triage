from django.http import JsonResponse

from stock.models import Item

SORTABLE = {"sku": "sku", "qty": "-quantity", "recent": "-updated"}


def item_list(request):
    key = request.GET.get("sort", "recent")
    if key not in SORTABLE:
        key = "recent"
    items = Item.objects.order_by(SORTABLE[key]).values("sku", "quantity")
    return JsonResponse({"items": list(items)})
