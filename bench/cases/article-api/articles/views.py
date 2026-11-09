from django.http import JsonResponse

from articles.models import Article


def article_list(request):
    sort = request.GET.get("sort", "-published")
    rows = Article.objects.order_by(sort).values("id", "title", "published")[:50]
    return JsonResponse({"results": list(rows)})
