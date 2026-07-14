# Guide du responsable 📊

*Pour ceux qui configurent et supervisent un établissement. Groupe Odoo :
« Responsable file d'attente » (inclut les droits d'agent). Vous ne voyez
que VOS établissements — l'isolation entre abonnés est garantie par le
système.*

## 1. Mettre en place un site

**Astuce onboarding** : créez votre établissement via **Configuration →
Nouvel établissement** (assistant) en choisissant votre **secteur d'activité**
— les services types sont pré-remplis (Santé, Administration, Banque,
Transport, Télécom, Commerce). Sur un site existant, le bouton
**Ajouter des services (modèle)** fait de même.

**Configuration → Sites → Nouveau** (manuel) :

1. Nom, adresse — le site appartient à votre société.
2. Onglet **Services** : créez vos services (nom + préfixe de numérotation,
   ex. « B » → B-001, B-002…). Par service, deux canaux optionnels :
   - **Tickets à distance** : les clients déjà venus peuvent prendre un
     ticket sans être sur place. Deux niveaux : l'interrupteur **du site**
     (fiche du site, coupe tout d'un coup) puis le réglage **de chaque
     service** — le distant n'est ouvert que si les deux le permettent ;
   - **Rendez-vous** : créneaux réservables (durée, capacité par créneau,
     quota de RDV actifs par client, plages d'ouverture par jour) ;
   - **Tarification** : cochez « Paiement requis » et saisissez le tarif —
     chaque ticket naît alors « paiement en attente ». Le client paie depuis
     l'application (mobile money) ou vous encaissez au guichet (bouton
     **Encaisser** sur le ticket). Le filtre **À payer** liste les impayés.
3. Onglet **Guichets** : créez les postes. En choisissant le site, les
   services sont pré-remplis — ajustez qui dessert quoi. L'« agent
   titulaire » est l'affectation par défaut ; la présence réelle se voit en
   temps réel : les agents **se connectent** à leur guichet depuis « Ma
   console » (plusieurs agents possibles par guichet), et le tableau de
   bord affiche qui est connecté où.
4. Onglet **QR d'entrée (à imprimer)** : le bouton **« Télécharger l'affiche
   QR (PDF) »** génère une affiche prête à imprimer (QR + nom du site +
   consigne) à poser à l'entrée. Les clients la scannent *dans l'app* pour
   prendre leur ticket. **Régénérer le QR** invalide l'ancien (affiche
   perdue/volée). Le bouton **Télécharger le QR** est aussi dans l'en-tête
   de la fiche.

Depuis la fiche du site, deux écrans publics à mettre en plein écran :

- **Écran d'affichage** : salle d'attente — numéros appelés (le nouvel appel
  clignote **et émet un carillon**), prochains appels et **file d'attente par
  service** ;
- **Borne tactile** : prise de ticket pour les clients sans smartphone —
  touchez un service, le ticket s'affiche avec position, attente estimée et,
  pour un service payant, le **montant à régler au guichet**.

*(Le carillon de l'écran d'affichage nécessite que le navigateur autorise le
son — en mode plein écran/kiosque, ou après un premier appui sur l'écran.)*

Les deux affichent automatiquement le QR « installez l'app » quand une
version est publiée par l'administrateur.

## 2. Superviser au quotidien

**Tableau de bord** (actualisé toutes les 5 s) : KPIs du jour, état des
services avec seuils visuels (orange ≥ 4 en attente ou ≥ 15 min estimées,
rouge ≥ 8 ou ≥ 30 min) et guichets actionnables — vous pouvez appeler ou
clôturer vous-même en cas de coup de feu.

**Statistiques** : analyse pivot/graphique sur l'historique (attente réelle,
durée de service, répartition par canal — sur place / à distance / borne /
RDV — taux d'absence…).

## 3. Suivre les clients mobiles

**Configuration → Clients mobiles** : vous voyez uniquement les clients
ayant au moins un ticket chez vous, avec leur historique (bouton Tickets).
**Archiver** un client bloque immédiatement sa session mobile (abus).
Les clients s'inscrivent eux-mêmes dans l'app — vous n'avez rien à créer.

## 4. Traçabilité

Chaque fiche (site, file, guichet, client, ticket) porte un **chatter** :
les changements sensibles y sont historisés automatiquement — qui a activé
les tickets à distance, réaffecté un agent, régénéré un QR, et quand.
Utilisez-le aussi pour vos notes internes.

## Réglages transverses (via l'administrateur)

Le plafond de tickets par client, la durée de session mobile, le seuil de
notification « bientôt votre tour » et le délai d'expiration des RDV sont
des réglages globaux de la plateforme : voyez l'administrateur
(Configuration → Paramètres).
