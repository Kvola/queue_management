# Guide de l'agent de guichet 🎫

*Pour le personnel qui appelle et sert les clients. Groupe Odoo :
« Agent de guichet ».*

## Votre poste de travail : le Tableau de bord

Menu **File d'attente → Tableau de bord**. Vous y voyez en direct
(actualisation toutes les 5 secondes) :

- les **KPIs du jour** : en attente, servis, attente moyenne, taux d'absence ;
- les **files** : combien attendent, le prochain numéro, l'attente estimée —
  une file passe en **orange puis rouge** quand elle se charge ;
- les **guichets** avec leurs boutons d'action.

Alternative : menu **Guichets** → vue kanban « console » (une grande carte
par guichet, gros numéro en cours).

## Le cycle d'un client

Sur la carte de votre guichet :

1. **Appeler le suivant** — le système choisit automatiquement le bon ticket
   (priorité, ordre d'arrivée, rendez-vous dont l'heure est passée remontés
   en tête). Le client est notifié sur son téléphone (« C'est à vous ! »)
   et l'écran de salle affiche son numéro en clignotant.
2. Le client arrive → **Démarrer** (début de la prise en charge).
3. Fin du service → **Terminer**.

Cas particuliers, tant que le ticket est « appelé » :

- **Rappeler** — ré-annonce le numéro (écran + notification) sans rien changer.
- **Absent** — le client ne s'est pas présenté : le ticket est clos en
  « Absent » et vous pouvez appeler le suivant.

## Garde-fous (c'est normal si…)

- *« Terminez d'abord le client en cours »* : un guichet ne traite qu'un
  client à la fois — terminez (ou marquez absent) avant de rappeler.
- *« Aucun client en attente »* : la file est vide, le bouton se réactive
  dès qu'un ticket arrive.
- *« Ce guichet ne dessert aucune file »* : la fiche du guichet n'a pas de
  « Files desservies » — voyez votre responsable.

## Bon à savoir

- Un ticket **sans client** (pas de nom) vient de la **borne** : le client
  suit son tour sur l'écran de salle, pas sur un téléphone.
- Les tickets **« À distance »** ont été pris avant l'arrivée du client :
  s'il ne répond pas à l'appel, « Absent » puis au suivant — il pourra
  reprendre un ticket.
- Un **rendez-vous** enregistré à l'accueil entre dans la file avec une
  priorité au moins « haute » si son heure est passée.
- Vous pouvez aussi créer un ticket manuellement (menu Tickets → Nouveau)
  pour un client au comptoir : choisissez la file, le numéro est attribué
  automatiquement.
