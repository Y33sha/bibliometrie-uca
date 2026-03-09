#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validateur de signatures institutionnelles pour l'Université Clermont Auvergne
Analyse les affiliations et détecte les erreurs par rapport aux règles officielles
"""

import json
import re
import csv
import sys
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from unicodedata import normalize
import difflib


@dataclass
class ValidationResult:
    """Résultat de validation d'une signature"""
    signature_originale: str
    est_uca: bool
    est_chu: bool
    est_correcte: bool
    labo_identifie: Optional[str] = None
    labo_ror: Optional[str] = None
    erreurs: List[str] = field(default_factory=list)
    forme_correcte: Optional[str] = None
    confiance_identification: float = 0.0


class SignatureValidator:
    """Validateur de signatures institutionnelles UCA"""
    
    def __init__(self, labos_json_path: str, config_json_path: str = None):
        """
        Initialise le validateur avec les données des laboratoires
        
        Args:
            labos_json_path: Chemin vers le fichier JSON des laboratoires
            config_json_path: Chemin vers le fichier de configuration (optionnel)
        """
        with open(labos_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.labos = data['labos']
        
        # Charge la configuration externe si fournie, sinon utilise les valeurs par défaut
        if config_json_path and os.path.exists(config_json_path):
            with open(config_json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.noms_universite_acceptes = config['universite']['formes_acceptees']
            self.noms_universite_obsoletes = config['universite']['formes_obsoletes']
            self.formes_inp = config['inp']['formes_acceptees']
            self.chu_indicateurs = config['chu']['indicateurs_chu']
            self.chu_indicateurs_clermont = config['chu']['indicateurs_clermont']
            self.chu_entites_clermont = config['chu']['entites_chu_clermont']
            
            # Patterns pour le code postal
            patterns = config['localisation']['patterns']
            self.pattern_postal_correct = patterns['postal_correct']
            self.pattern_postal_avec_virgule = patterns['postal_avec_virgule']
            self.pattern_postal_partiel = patterns['postal_partiel']

            # Configuration des tutelles (nouveau format avec formes)
            self.tutelles_config = config.get('tutelles_courantes', {})
        else:
            # Valeurs par défaut (rétrocompatibilité)
            self.noms_universite_acceptes = [
                "Université Clermont Auvergne",
                "Clermont Auvergne University",
                "University Clermont Auvergne"
            ]
            
            self.noms_universite_obsoletes = [
                "Université Clermont-Auvergne",
                "Université d'Auvergne",
                "Université Blaise Pascal",
                "UdA",
                "UBP",
                "UCA"
            ]
            
            self.formes_inp = [
                "Clermont Auvergne INP",
                "Clermont Auvergne Institut National Polytechnique"
            ]
            
            self.chu_indicateurs = [
                r'\bchu\b',
                r'centre hospitalier universitaire',
                r'university hospital'
            ]
            
            self.chu_indicateurs_clermont = [
                'clermont',
                'estaing',
                'montpied'
            ]
            
            self.chu_entites_clermont = [
                'centre jean perrin',
                'crnh',
                'crnh auvergne',
                'centre de recherche en nutrition humaine'
            ]
            
            # Patterns pour le code postal
            self.pattern_postal_correct = r"F-63000\s+Clermont[-–—]\s*Ferrand"
            self.pattern_postal_avec_virgule = r"F-63000\s*,\s*Clermont[-–—]\s*Ferrand"
            self.pattern_postal_partiel = r"63000\s+Clermont[-–—]?\s*Ferrand"

            # Pas de config tutelles en mode par défaut
            self.tutelles_config = {}
        
    def normalize_text(self, text: str) -> str:
        """
        Normalise le texte pour la comparaison (gère les accents, espaces, etc.)
        
        Args:
            text: Texte à normaliser
            
        Returns:
            Texte normalisé
        """
        if not text:
            return ""
        
        # Normalisation Unicode (décompose les caractères accentués)
        text = normalize('NFKD', text)
        
        # Nettoie les espaces multiples et les tirets
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[-–—]', '-', text)
        
        return text.strip()

    def _chercher_tutelle_dans_signature(self, tutelle_key: str, signature_norm: str) -> Tuple[bool, Optional[str], bool]:
        """
        Cherche une tutelle dans une signature en utilisant ses formes configurées.
        Même logique de matching que identifier_laboratoire() : word boundaries pour
        les formes courtes, sous-chaîne pour les formes longues.

        Args:
            tutelle_key: Nom canonique de la tutelle (clé dans tutelles_config)
            signature_norm: Signature déjà normalisée via normalize_text()

        Returns:
            Tuple (matched, forme_trouvée, est_acceptée)
        """
        sig_lower = signature_norm.lower()

        # Si la tutelle est dans la config, utiliser ses formes
        if tutelle_key in self.tutelles_config:
            config_tutelle = self.tutelles_config[tutelle_key]
            formes = config_tutelle.get('formes', {})

            # Détecte si UCA est présente (pour les formes ambiguës)
            uca_presente = any(
                self.normalize_text(nom).lower() in sig_lower
                for nom in self.noms_universite_acceptes + self.noms_universite_obsoletes
            )

            for forme, props in formes.items():
                forme_norm = self.normalize_text(forme).lower()

                # Forme ambiguë sans UCA → skip
                if props.get('ambigu', False) and not uca_presente:
                    continue

                # Matching
                matched = False
                if len(forme_norm) <= 6:
                    # Acronymes courts : word boundaries
                    pattern = r'(?<![a-z0-9])' + re.escape(forme_norm) + r'(?![a-z0-9])'
                    if re.search(pattern, sig_lower, re.IGNORECASE):
                        matched = True
                else:
                    # Noms longs : sous-chaîne
                    if forme_norm in sig_lower:
                        matched = True

                if matched:
                    return True, forme, props.get('accepte', True)

            # Aucune forme n'a matché
            return False, None, True

        # Fallback : tutelle non configurée, matching direct par sous-chaîne
        tutelle_norm = self.normalize_text(tutelle_key).lower()
        if tutelle_norm in sig_lower:
            return True, tutelle_key, True

        return False, None, True

    def fuzzy_match(self, text: str, candidates: List[str], threshold: float = 0.85) -> Tuple[Optional[str], float]:
        """
        Trouve la meilleure correspondance floue parmi une liste de candidats
        
        Args:
            text: Texte à matcher
            candidates: Liste de candidats
            threshold: Seuil de similarité minimum
            
        Returns:
            Tuple (meilleur candidat, score de similarité)
        """
        text_norm = self.normalize_text(text).lower()
        best_match = None
        best_score = 0.0
        
        for candidate in candidates:
            candidate_norm = self.normalize_text(candidate).lower()
            
            # Calcul de similarité avec SequenceMatcher
            score = difflib.SequenceMatcher(None, text_norm, candidate_norm).ratio()
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        if best_score >= threshold:
            return best_match, best_score
        
        return None, best_score
    
    def identifier_laboratoire(self, signature: str) -> Tuple[Optional[str], Optional[str], float]:
        """
        Identifie le laboratoire dans une signature
    
        Args:
            signature: Signature à analyser
        
        Returns:
            Tuple (ROR ID du labo, nom du labo, score de confiance)
        """
        signature_norm = self.normalize_text(signature)
        sig_lower = signature_norm.lower()
    
        # Détecte si UCA est présente (pour les formes ambiguës)
        uca_presente = any(
            self.normalize_text(nom).lower() in sig_lower
            for nom in self.noms_universite_acceptes + self.noms_universite_obsoletes
        )
    
        # Parcourir tous les laboratoires
        for ror_id, labo_data in self.labos.items():
            for forme, props in labo_data.get('formes', {}).items():
                forme_norm = self.normalize_text(forme).lower()
            
                # ÉTAPE 1 : Dois-je reconnaître cette forme ?
                if props.get('ambigu', False) and not uca_presente:
                    # Forme ambiguë sans UCA → skip
                    continue
            
                # ÉTAPE 2 : Cette forme matche-t-elle dans la signature ?
                matched = False
            
                if len(forme_norm) <= 6:
                    # Acronymes courts : word boundaries
                    pattern = r'(?<![a-z0-9])' + re.escape(forme_norm) + r'(?![a-z0-9])'
                    if re.search(pattern, sig_lower, re.IGNORECASE):
                        matched = True
                else:
                    # Noms longs : présence suffit
                    if forme_norm in sig_lower:
                        matched = True
            
                if not matched:
                    continue
            
                # ÉTAPE 3 : Match trouvé ! Retourner avec confiance appropriée
                if props.get('accepte', True):
                    # Forme acceptée : confiance pleine
                    confiance = 0.8 if props.get('ambigu', False) else 1.0
                else:
                    # Forme rejetée : confiance moindre (génèrera une erreur)
                    confiance = 0.9
            
                forme_affichage = labo_data.get('forme_preferee', forme)
                return ror_id, forme_affichage, confiance
    
        # Aucun laboratoire identifié
        return None, None, 0.0
    
    def verifier_nom_universite(self, signature: str) -> List[str]:
        """
        Vérifie la présence et la forme du nom de l'université
        
        Args:
            signature: Signature à analyser
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        signature_norm = self.normalize_text(signature)
        
        # Vérifie si un nom accepté est présent
        nom_trouve = False
        for nom in self.noms_universite_acceptes:
            if self.normalize_text(nom).lower() in signature_norm.lower():
                nom_trouve = True
                break
        
        if not nom_trouve:
            # Vérifie si un nom obsolète est utilisé
            for nom in self.noms_universite_obsoletes:
                if self.normalize_text(nom).lower() in signature_norm.lower():
                    erreurs.append(f"Nom obsolète de l'université utilisé: '{nom}'")
                    return erreurs
            
            erreurs.append("Nom de l'université absent ou incorrect")
        
        return erreurs
    
    def verifier_inp(self, signature: str, labo_ror: str) -> List[str]:
        """
        Vérifie la présence de "Clermont Auvergne INP" pour les labos concernés
        
        Args:
            signature: Signature à analyser
            labo_ror: ROR ID du laboratoire
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        
        if not labo_ror or labo_ror not in self.labos:
            return erreurs
        
        labo_data = self.labos[labo_ror]
        est_labo_inp = labo_data.get('INP', False)
        
        signature_norm = self.normalize_text(signature)
        
        # Vérifie la présence de l'une des formes INP acceptées
        contient_inp = any(forme.lower() in signature_norm.lower() for forme in self.formes_inp)
        
        if est_labo_inp and not contient_inp:
            erreurs.append("'Clermont Auvergne INP' manquant (requis pour ce laboratoire)")
        elif not est_labo_inp and contient_inp:
            erreurs.append("'Clermont Auvergne INP' présent mais non requis pour ce laboratoire")
        
        return erreurs
    
    def verifier_tutelles(self, signature: str, labo_ror: str) -> List[str]:
        """
        Vérifie la présence et l'ordre des tutelles
        
        Args:
            signature: Signature à analyser
            labo_ror: ROR ID du laboratoire
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        
        if not labo_ror or labo_ror not in self.labos:
            return erreurs
        
        labo_data = self.labos[labo_ror]
        tutelles_attendues = labo_data['tutelles']
        
        # Retire "Université Clermont Auvergne" de la liste pour la vérification
        # (déjà vérifiée séparément)
        tutelles_a_verifier = [t for t in tutelles_attendues if t != "Université Clermont Auvergne"]
        
        signature_norm = self.normalize_text(signature)

        # Vérifie la présence de chaque tutelle via ses formes configurées
        tutelles_manquantes = []
        for tutelle in tutelles_a_verifier:
            matched, forme, est_acceptee = self._chercher_tutelle_dans_signature(tutelle, signature_norm)
            if not matched:
                tutelles_manquantes.append(tutelle)
            elif not est_acceptee:
                erreurs.append(f"Forme rejetée de la tutelle '{tutelle}': '{forme}'")

        if tutelles_manquantes:
            erreurs.append(f"Tutelle(s) manquante(s): {', '.join(tutelles_manquantes)}")

        return erreurs
    
    def verifier_ordre_elements(self, signature: str, labo_ror: str) -> List[str]:
        """
        Vérifie l'ordre des éléments dans la signature
        
        Args:
            signature: Signature à analyser
            labo_ror: ROR ID du laboratoire
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        
        if not labo_ror or labo_ror not in self.labos:
            return erreurs
        
        labo_data = self.labos[labo_ror]
        signature_norm = self.normalize_text(signature).lower()
        
        # Trouve les positions des éléments clés
        positions = {}
        
        # Position de l'université
        for nom in self.noms_universite_acceptes + self.noms_universite_obsoletes:
            nom_norm = self.normalize_text(nom).lower()
            pos = signature_norm.find(nom_norm)
            if pos != -1:
                positions['universite'] = pos
                break
        
        # Position du nom du labo
        formes_acceptees = [f for f, p in labo_data.get('formes', {}).items() if p.get('accepte', True)]
        for forme in formes_acceptees:
            forme_norm = self.normalize_text(forme).lower()
            pos = signature_norm.find(forme_norm)
            if pos != -1:
                positions['labo'] = pos
                break
        
        # Position des tutelles (hors UCA) — via formes configurées
        tutelles_a_verifier = [t for t in labo_data['tutelles'] if t != "Université Clermont Auvergne"]
        positions['tutelles'] = []
        for tutelle in tutelles_a_verifier:
            matched, forme_trouvee, _ = self._chercher_tutelle_dans_signature(tutelle, self.normalize_text(signature))
            if matched and forme_trouvee:
                forme_norm = self.normalize_text(forme_trouvee).lower()
                pos = signature_norm.find(forme_norm)
                if pos != -1:
                    positions['tutelles'].append((tutelle, pos))
        
        # Position de INP si applicable
        if labo_data.get('INP', False):
            pos = signature_norm.find('clermont auvergne inp')
            if pos != -1:
                positions['inp'] = pos
        
        # Vérification de l'ordre
        # 1. L'université doit être en premier
        if 'universite' in positions and 'labo' in positions:
            if positions['universite'] > positions['labo']:
                erreurs.append("Ordre incorrect: le nom de l'université doit apparaître avant le nom du laboratoire")
        
        if 'universite' in positions and positions['tutelles']:
            for tutelle, pos in positions['tutelles']:
                if positions['universite'] > pos:
                    erreurs.append(f"Ordre incorrect: le nom de l'université doit apparaître avant la tutelle '{tutelle}'")
                    break
        
        # 2. INP doit être après l'université mais avant les autres tutelles
        if 'inp' in positions and 'universite' in positions:
            if positions['inp'] < positions['universite']:
                erreurs.append("Ordre incorrect: 'Clermont Auvergne INP' doit apparaître après le nom de l'université")
        
        # 3. Les tutelles doivent être avant le nom du labo
        if 'labo' in positions and positions['tutelles']:
            for tutelle, pos in positions['tutelles']:
                if pos > positions['labo']:
                    erreurs.append(f"Ordre incorrect: la tutelle '{tutelle}' doit apparaître avant le nom du laboratoire")
                    break
        
        return erreurs
    
    def verifier_code_postal(self, signature: str) -> List[str]:
        """
        Vérifie le format du code postal et de la ville
    
        Args:
            signature: Signature à analyser
        
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        signature_norm = self.normalize_text(signature)
    
        # Normaliser TOUS les types de tirets vers le tiret standard
        # Tiret cadratin (—), demi-cadratin (–), insécable, etc.
        signature_norm = re.sub(r'[-–—‐‑‒―−]', '-', signature_norm)
    
        # Vérifie le format correct (sans virgule)
        if re.search(self.pattern_postal_correct, signature_norm, re.IGNORECASE):
            return erreurs
    
        # Vérifie le format avec virgule (toléré)
        if re.search(self.pattern_postal_avec_virgule, signature_norm, re.IGNORECASE):
            return erreurs
    
        # Vérifie si au moins le format partiel est présent
        if re.search(self.pattern_postal_partiel, signature_norm, re.IGNORECASE):
            if not re.search(r'\bF-63000\b', signature_norm, re.IGNORECASE):
                erreurs.append("Préfixe 'F-' manquant devant le code postal")
        else:
            # Vérifie la présence de Clermont-Ferrand au moins
            if 'clermont' not in signature_norm.lower():
                erreurs.append("Code postal et ville manquants ou incorrects")
            else:
                erreurs.append("Format du code postal incorrect (attendu: F-63000 Clermont-Ferrand)")
    
        return erreurs
    
    def verifier_france(self, signature: str) -> List[str]:
        """
        Vérifie la présence de "France" à la fin
        
        Args:
            signature: Signature à analyser
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        signature_norm = self.normalize_text(signature).lower()
        
        # Retire la ponctuation et espaces en fin de chaîne
        signature_clean = signature_norm.rstrip('.,;:!?()[]{}"\' \t\n\r')
        
        if not signature_clean.endswith('france'):
            erreurs.append("'France' manquant en fin de signature")
        
        return erreurs
    
    def verifier_forme_rejetee_labo(self, signature: str, labo_ror: str) -> List[str]:
        """
        Vérifie si une forme rejetée du nom de labo est utilisée
        
        Args:
            signature: Signature à analyser
            labo_ror: ROR ID du laboratoire
            
        Returns:
            Liste des erreurs détectées
        """
        erreurs = []
        
        if not labo_ror or labo_ror not in self.labos:
            return erreurs
        
        labo_data = self.labos[labo_ror]
        signature_norm = self.normalize_text(signature).lower()
        
        # Parcourir toutes les formes et vérifier celles qui sont rejetées
        for forme, props in labo_data.get('formes', {}).items():
            if not props.get('accepte', True):  # C'est une forme rejetée
                forme_norm = self.normalize_text(forme).lower()
                
                # Vérification avec word boundaries pour les acronymes courts
                if len(forme_norm) <= 6:
                    pattern = r'(?<![a-z0-9])' + re.escape(forme_norm) + r'(?![a-z0-9])'
                    if re.search(pattern, signature_norm, re.IGNORECASE):
                        erreurs.append(f"Forme rejetée du nom de laboratoire: '{forme}'")
                else:
                    # Pour les noms longs, présence suffit
                    if forme_norm in signature_norm:
                        erreurs.append(f"Forme rejetée du nom de laboratoire: '{forme}'")

        
        return erreurs
    
    def generer_signature_correcte(self, labo_ror: str, partenaires_supplementaires: List[str] = None) -> str:
        """
        Génère la signature correcte pour un laboratoire donné
        
        Args:
            labo_ror: ROR ID du laboratoire
            partenaires_supplementaires: Liste de partenaires supplémentaires (ex: CHU)
            
        Returns:
            Signature correcte formatée
        """
        if labo_ror not in self.labos:
            return ""
        
        labo_data = self.labos[labo_ror]
        
        # Si une signature pré-formatée existe, l'utiliser
        if 'signature' in labo_data:
            return labo_data['signature']
        
        # Sinon, construire la signature
        elements = []
        
        # Université (toujours en premier)
        elements.append("Université Clermont Auvergne")
        
        # Clermont Auvergne INP si nécessaire
        if labo_data.get('INP', False):
            elements.append("Clermont Auvergne INP")
        
        # Partenaires supplémentaires (ex: CHU)
        if partenaires_supplementaires:
            elements.extend(partenaires_supplementaires)
        
        # Tutelles (sauf UCA déjà ajoutée) — utilise la première forme acceptée non ambiguë
        tutelles = [t for t in labo_data['tutelles'] if t != "Université Clermont Auvergne"]
        for t in tutelles:
            if t in self.tutelles_config:
                config_t = self.tutelles_config[t]
                forme = next(
                    (f for f, p in config_t.get('formes', {}).items()
                     if p.get('accepte', True) and not p.get('ambigu', False)),
                    t
                )
                elements.append(forme)
            else:
                elements.append(t)
        
        # Nom du laboratoire (première forme acceptée non ambiguë de préférence)
        formes = labo_data.get('formes', {})
        nom_labo = next(
            (f for f, p in formes.items() if p.get('accepte', True) and not p.get('ambigu', False)),
            next((f for f, p in formes.items() if p.get('accepte', True)), '')
        )
        elements.append(nom_labo)
        
        # Code postal et ville
        elements.append("F-63000 Clermont-Ferrand")
        
        # Pays
        elements.append("France")
        
        return ", ".join(elements)
    
    def est_signature_chu(self, signature: str) -> bool:
        """
        Détermine si une signature concerne le CHU de Clermont-Ferrand
        
        Args:
            signature: Signature à analyser
            
        Returns:
            True si la signature concerne le CHU, False sinon
        """
        signature_norm = self.normalize_text(signature).lower()
        
        # Vérifie d'abord la présence d'une entité membre du CHU Clermont
        # (Centre Jean Perrin, CRNH, etc.)
        for entite in self.chu_entites_clermont:
            if entite.lower() in signature_norm:
                return True
        
        # Sinon, vérifie la combinaison indicateur CHU générique + indicateur Clermont
        # Doit avoir au moins un indicateur CHU
        a_indicateur_chu = False
        for pattern in self.chu_indicateurs:
            if re.search(pattern, signature_norm):
                a_indicateur_chu = True
                break
        
        if not a_indicateur_chu:
            return False
        
        # ET au moins un indicateur Clermont
        for indicateur in self.chu_indicateurs_clermont:
            if indicateur in signature_norm:
                return True
        
        return False
    
    def est_signature_uca(self, signature: str) -> bool:
        """
        Détermine si une signature concerne l'UCA
        
        Args:
            signature: Signature à analyser
            
        Returns:
            True si la signature concerne l'UCA, False sinon
        """
        signature_norm = self.normalize_text(signature).lower()
        
        # Vérifie la présence du nom de l'université (accepté ou obsolète)
        nom_universite_present = False
        for nom in self.noms_universite_acceptes + self.noms_universite_obsoletes:
            if self.normalize_text(nom).lower() in signature_norm:
                nom_universite_present = True
                break
        
        # Si nom de l'université présent → UCA
        if nom_universite_present:
            return True
        
        # Vérifie la présence d'un laboratoire UCA → UCA même sans nom d'université
        labo_ror, _, _ = self.identifier_laboratoire(signature)
        if labo_ror:
            return True
        
        # Si c'est juste un CHU sans labo UCA et sans nom université → pas UCA
        if self.est_signature_chu(signature):
            return False
        
        # Sinon, pas UCA
        return False
    
    def valider_signature(self, signature: str) -> ValidationResult:
        """
        Valide une signature complète
        
        Args:
            signature: Signature à valider
            
        Returns:
            Résultat de validation avec toutes les erreurs détectées
        """
        result = ValidationResult(signature_originale=signature, est_uca=False, est_chu=False, est_correcte=False)
        
        # Vérifie si c'est une signature CHU
        result.est_chu = self.est_signature_chu(signature)
        
        # Vérifie si c'est une signature UCA
        result.est_uca = self.est_signature_uca(signature)
        
        if not result.est_uca:
            return result
        
        # Identifie le laboratoire
        labo_ror, labo_nom, confiance = self.identifier_laboratoire(signature)
        result.labo_ror = labo_ror
        result.labo_identifie = labo_nom
        result.confiance_identification = confiance
        
        if not labo_ror:
            result.erreurs.append("Laboratoire non identifié")
            return result
        
        # Exécute toutes les vérifications
        result.erreurs.extend(self.verifier_nom_universite(signature))
        result.erreurs.extend(self.verifier_inp(signature, labo_ror))
        result.erreurs.extend(self.verifier_tutelles(signature, labo_ror))
        result.erreurs.extend(self.verifier_ordre_elements(signature, labo_ror))
        result.erreurs.extend(self.verifier_forme_rejetee_labo(signature, labo_ror))
        result.erreurs.extend(self.verifier_code_postal(signature))
        result.erreurs.extend(self.verifier_france(signature))
        
        # Génère la forme correcte
        result.forme_correcte = self.generer_signature_correcte(labo_ror)
        
        # Détermine si la signature est correcte
        result.est_correcte = len(result.erreurs) == 0
        
        return result


def traiter_csv(input_csv: str, output_csv: str, labos_json: str, config_json: str = None):
    """
    Traite un fichier CSV d'affiliations et produit un rapport
    
    Args:
        input_csv: Chemin du fichier CSV d'entrée
        output_csv: Chemin du fichier CSV de sortie
        labos_json: Chemin du fichier JSON des laboratoires
        config_json: Chemin du fichier de configuration (optionnel)
    """
    # Vérifie que les fichiers d'entrée existent
    import os
    if not os.path.exists(input_csv):
        print(f"Erreur: Le fichier d'entrée '{input_csv}' n'existe pas.")
        sys.exit(1)
    if not os.path.exists(labos_json):
        print(f"Erreur: Le fichier de configuration '{labos_json}' n'existe pas.")
        sys.exit(1)
    
    # Cherche le fichier de config dans le même répertoire si non fourni
    if config_json is None:
        config_json = os.path.join(os.path.dirname(labos_json), 'config_validation.json')
    
    try:
        validator = SignatureValidator(labos_json, config_json)
    except Exception as e:
        print(f"Erreur lors du chargement de la configuration des laboratoires: {e}")
        sys.exit(1)
    
    # Lit le CSV d'entrée avec plusieurs encodages possibles
    rows = None
    for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            with open(input_csv, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            print(f"Fichier lu avec succès (encodage: {encoding})")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"Erreur lors de la lecture du fichier CSV avec encodage {encoding}: {e}")
            continue
    
    if rows is None:
        print(f"Erreur: Impossible de lire le fichier '{input_csv}' avec les encodages courants.")
        print("Encodages testés: utf-8, utf-8-sig, latin-1, cp1252")
        sys.exit(1)
    
    # Vérifie que la colonne 'raw_affiliation_string' existe
    if rows and 'raw_affiliation_string' not in rows[0]:
        print(f"\nErreur: La colonne 'raw_affiliation_string' n'existe pas dans le fichier CSV.")
        print(f"Colonnes disponibles: {', '.join(rows[0].keys())}")
        sys.exit(1)
    
    print(f"Analyse de {len(rows)} lignes...")
    
    # Traite chaque ligne
    results = []
    for row in rows:
        signature = row.get('raw_affiliation_string', '')
        
        if not signature:
            continue
        
        validation = validator.valider_signature(signature)
        
        # Ajoute les informations de validation à la ligne
        result_row = row.copy()
        result_row['est_uca'] = 'Oui' if validation.est_uca else 'Non'
        result_row['est_chu'] = 'Oui' if validation.est_chu else 'Non'
        result_row['est_correcte'] = 'Oui' if validation.est_correcte else 'Non'
        result_row['laboratoire_identifie'] = validation.labo_identifie or ''
        result_row['labo_ror'] = validation.labo_ror or ''
        result_row['confiance_identification'] = f"{validation.confiance_identification:.2f}"
        result_row['erreurs'] = ' | '.join(validation.erreurs)
        result_row['forme_correcte'] = validation.forme_correcte or ''
        
        results.append(result_row)
    
    # Écrit le CSV de sortie
    if results:
        fieldnames = list(results[0].keys())
        try:
            with open(output_csv, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)
        except Exception as e:
            print(f"\nErreur lors de l'écriture du fichier de sortie: {e}")
            sys.exit(1)
    else:
        print("\nAucune donnée à écrire dans le fichier de sortie.")
        sys.exit(0)
    
    # Affiche un résumé
    total = len(results)
    uca = sum(1 for r in results if r['est_uca'] == 'Oui')
    correctes = sum(1 for r in results if r['est_correcte'] == 'Oui')
    
    print(f"\n{'='*60}")
    print(f"RÉSUMÉ DE L'ANALYSE")
    print(f"{'='*60}")
    print(f"Total de signatures analysées: {total}")
    print(f"Signatures UCA: {uca} ({100*uca/total:.1f}%)")
    print(f"Signatures UCA correctes: {correctes} ({100*correctes/uca if uca > 0 else 0:.1f}%)")
    print(f"\nRapport détaillé généré: {output_csv}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("Usage: python signature_validator.py <input.csv> <output.csv> <labos.json> [config.json]")
        print("\nArguments:")
        print("  input.csv   : Fichier CSV d'entrée avec les signatures à analyser")
        print("  output.csv  : Fichier CSV de sortie avec les résultats")
        print("  labos.json  : Fichier de configuration des laboratoires")
        print("  config.json : (Optionnel) Fichier de configuration des variantes de noms")
        print("                Si non fourni, cherche 'config_validation.json' dans le même répertoire")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_csv = sys.argv[2]
    labos_json = sys.argv[3]
    config_json = sys.argv[4] if len(sys.argv) == 5 else None
    
    traiter_csv(input_csv, output_csv, labos_json, config_json)