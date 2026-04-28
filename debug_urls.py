#!/usr/bin/env python
"""
Debug script to check Django URL configuration
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.conf import settings
from django.urls import get_resolver

def debug_urls():
    print("=== Django URL Debug ===")
    print(f"ROOT_URLCONF: {settings.ROOT_URLCONF}")
    print(f"DEBUG: {settings.DEBUG}")
    print(f"BASE_DIR: {settings.BASE_DIR}")

    print("\n=== URL Patterns ===")
    resolver = get_resolver()
    for pattern in resolver.url_patterns:
        print(f"Pattern: {pattern}")

    print("\n=== Testing URL Resolution ===")
    from django.urls import resolve, Resolver404
    test_urls = [
        '/notifications/test/',
        '/notifications/ch-notification/',
        '/api/',
        '/admin/',
    ]

    for url in test_urls:
        try:
            match = resolve(url)
            print(f"OK {url} -> {match.url_name} ({match.func})")
        except Resolver404:
            print(f"NOT FOUND {url} -> Not found")

if __name__ == '__main__':
    debug_urls()