# Guide du responsable 📊

*Pour ceux qui configurent et supervisent un établissement. Groupe Odoo :
« Responsable file d'attente » (inclut les droits d'agent). Vous ne voyez
que VOS établissements — l'isolation entre abonnés est garantie par le
système.*

## 1. Mettre en place un site

**Configuration → Sites → Nouveau** :

1. Nom, adresse — le site appartient à votre société.
2. Onglet **Files** : créez vos files (nom + préfixe de numérotation, ex.
   « B » → B-001, B-002…). Par file, deux canaux optionnels :
   - **Tickets à distance** : les clients déjà venus peuvent prendre un
     ticket sans être sur place ;
   - **Rendez-vous** : créneaux réservables (durée, capacité par créneau,
     quota de RDV actifs par client, plages d'ouverture par jour).
3. Onglet **Guichets** : créez les postes. En choisissant le site, les
   files sont pré-remplies — ajustez qui dessert quoi, affectez un agent.
4. Onglet **QR d'entrée (à imprimer)** : imprimez et affichez ce QR à
   l'entrée — c'est lui que les clients scannent *dans l'app* pour prendre
   leur ticket. **Régénérer le QR** invalide l'ancien (affiche perdue/volée).

Depuis la fiche du site, deux écrans publics à mettre en plein écran :

- **Écran d'affichage** : salle d'attente (numéros appelés, prochains) ;
- **Borne tactile** : prise de ticket pour les clients sans smartphone.

Les deux affichent automatiquement le QR « installez l'app » quand une
version est publiée par l'administrateur.

## 2. Superviser au quotidien

**Tableau de bord** (actualisé toutes les 5 s) : KPIs du jour, état des
files avec seuils visuels (orange ≥ 4 en attente ou ≥ 15 min estimées,
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
