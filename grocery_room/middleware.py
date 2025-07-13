# from django.http import HttpResponse
# from django.contrib.auth import authenticate


# class BasicAuthMiddleware:
#     def __init__(self, get_response):
#         self.get_response = get_response

#     def __call__(self, request):
#         if not request.user.is_authenticated:
#             auth_header = request.META.get('HTTP_AUTHORIZATION', '')
#             if not auth_header:
#                 return HttpResponse('Unauthorized', status=401)
#             try:
#                 auth_type, credentials = auth_header.split(' ', 1)
#                 if auth_type.lower() != 'basic':
#                     return HttpResponse('Unauthorized', status=401)
#                 import base64
#                 username, password = base64.b64decode(
#                     credentials).decode('utf-8').split(':', 1)
#                 user = authenticate(
#                     request, username=username, password=password)
#                 if user is None:
#                     return HttpResponse('Unauthorized', status=401)
#                 request.user = user
#             except (ValueError, UnicodeDecodeError):
#                 return HttpResponse('Unauthorized', status=401)
#         return self.get_response(request)
