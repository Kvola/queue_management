# Guide de l'agent de guichet 🎫

*Pour le personnel qui appelle et sert les clients. Groupe Odoo :
« Agent de guichet ».*

## Votre poste de travail : « Ma console »

Menu **File d'attente → Ma console** — l'écran plein format pensé pour le
guichet :

1. Choisissez votre guichet dans le sélecteur → **Rejoindre ce guichet**.
   Votre nom apparaît comme agent connecté (visible du responsable sur son
   tableau de bord). Plusieurs agents peuvent partager un même guichet
   (binôme, formation) ; rejoindre un guichet vous déconnecte
   automatiquement du précédent.
2. Le ticket en cours s'affiche en très grand, avec le service et le nom du
   client ; en dessous, le nombre en attente et le prochain numéro.
3. Les boutons suivent l'état : **Appeler le suivant** (guichet libre),
   puis **Démarrer / Rappeler / Absent**, puis **Terminer**.
4. **Quitter** en fin de poste — le guichet reste utilisable par les
   collègues connectés.

## L'autre vue : le Tableau de bord

Menu **File d'attente → Tableau de bord**. Vous y voyez en direct
(actualisation toutes les 5 secondes) :

- les **KPIs du jour** : en attente, servis, attente moyenne, taux d'absence ;
- les **services** : combien attendent, le prochain numéro, l'attente estimée —
  un service passe en **orange puis rouge** quand elle se charge ;
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
- **Transférer** — le client s'est trompé de service (ou vous le
  réorientez) : ouvrez son ticket → **Transférer** → choisissez le service
  de destination du site. Il garde son heure d'arrivée (pas de queue à
  refaire) et reçoit un numéro de la nouvelle file ; il est notifié.
- **Re-mettre en file** — le client marqué absent se présente finalement :
  ouvrez son ticket (menu Tickets) → **Re-mettre en file**. Il reprend sa
  place selon son heure d'arrivée d'origine (dans les 2 h qui suivent
  l'appel ; au-delà, il reprend un ticket).

- **Paiements** — service payant :
  - **Encaisser** (ticket « à payer ») : encaissement direct au comptoir → payé.
  - **Valider / Rejeter** (ticket « paiement à valider ») : le client a
    déclaré un paiement (Wave marchand, au guichet, ou preuve jointe) —
    vérifiez (numéro Wave crédité, espèces reçues, preuve) puis **Validez**,
    ou **Rejetez** s'il est invalide. Le menu **Opérations → Paiements à
    valider** liste tout ce qui attend votre confirmation.

À savoir : un ticket appelé resté **sans réponse** est automatiquement
marqué absent au bout de quelques minutes (délai réglé par
l'administrateur) — votre guichet ne reste jamais bloqué.

## Garde-fous (c'est normal si…)

- *« Terminez d'abord le client en cours »* : un guichet ne traite qu'un
  client à la fois — terminez (ou marquez absent) avant de rappeler.
- *« Aucun client en attente »* : la file est vide, le bouton se réactive
  dès qu'un ticket arrive.
- *« Ce guichet ne dessert aucun service »* : la fiche du guichet n'a pas de
  « Services desservis » — voyez votre responsable.

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
