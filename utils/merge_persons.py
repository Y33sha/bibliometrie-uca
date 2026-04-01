"""
Fonction unique de fusion de deux personnes.
Délègue au service persons. Ce module est conservé pour compatibilité.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.persons import merge_person
