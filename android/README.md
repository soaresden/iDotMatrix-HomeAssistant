# Pixel Météo pour Android

L'onglet **Météo** de Pixel Studio, seul, dans une appli Android : le téléphone pilote le cadre iDotMatrix
par Bluetooth, **sans Home Assistant ni PC**.

- L'heure en grand avec les secondes, le nom de la ville, la météo du jour (icône, température, max/min,
  risque de pluie) et en bas 4 heures au choix, les prochains jours ou le lever et le coucher du soleil.
- Jusqu'à 4 villes qui se relaient (toutes les 10 à 60 s), couleur de l'heure au choix, luminosité qui suit
  le soleil.
- Prévisions d'[Open-Meteo](https://open-meteo.com) (gratuit, sans clé) : il faut Internet sur le téléphone.
- Des écrans que tu remplis toi-même : « + » au-dessus de l'aperçu en ajoute un, vide ou déjà rempli (Météo,
  Saint du jour, Fêtes, Anniversaires, Compte à rebours, N'oubliez pas, Notes, Mot du jour, Philosophie,
  Citations marrantes, Dictons, Savoir inutile, Courage, Bien-être, Agenda, Journées mondiales), puis tu lui
  ajoutes ou enlèves des parties. Chaque écran a son temps, sa ville, et s'il veut ses heures (« N'oubliez pas »
  de 6 h à 10 h). Touche un numéro pour régler cet écran, ▶ pour les voir défiler.
- L'agenda vient des agendas du téléphone que tu coches, les anniversaires de tes contacts (si tu veux), et
  **Partager → Pixel Météo** depuis Keep (ou n'importe quelle appli) ajoute une note au cadre.
- Tout se règle sur l'aperçu : toucher une partie pour ne voir que ses réglages, la glisser (aimantée à la
  grille), ←→↑↓ pour la placer à la LED près, A↓/A↑ pour sa taille, un contour de couleur (du noir se voit
  avec), formats de la date (dd/mm, ddd d mmm…) et de l'heure (HH:mm:ss…).
- Les textes (citations, dictons, savoirs, mots…) sont dans `texts_fr.json` avec, pour chacun, d'où il vient.
- Les changements partent au cadre en direct, sans rien relancer.
- Sans Internet, l'heure continue (la dernière météo reste).

Chaque minute, l'appli envoie un seul GIF qui contient toute la minute (environ 4,5 Ko, 2 paquets Bluetooth,
un peu plus d'une seconde) : le cadre fait défiler les secondes et change de ville tout seul. Elle tourne en
arrière-plan (une notification « Pixel Météo » le montre), écran du téléphone éteint compris.

## Installer

1. Copie `PixelMeteo.apk` sur le téléphone (Android 7 ou plus récent) et ouvre-le.
2. Android demande d'autoriser l'installation depuis cette source (navigateur, gestionnaire de fichiers) :
   accepte. L'appli n'est pas sur le Play Store ; elle est signée avec une clé de développement.
   Play Protect peut prévenir que l'appli est inconnue : **Installer quand même**.
3. Ouvre **Pixel Météo**, accepte le Bluetooth (appareils à proximité) et les notifications.

## Utiliser

1. Allume le cadre et **ferme l'appli iDotMatrix** du téléphone (le cadre n'accepte qu'un téléphone à la fois).
2. **Chercher les cadres**, touche le tien, choisis sa taille (64×64 le plus souvent).
3. Tape une ville, **Chercher**, touche la bonne. **+ Ajouter une ville** pour en faire alterner plusieurs.
4. Règle l'affichage ; l'aperçu montre ce que fera le cadre, seconde par seconde.
5. **Afficher sur le cadre**. Touche **Ne pas limiter la batterie** pour qu'Android ne l'endorme pas.

Le téléphone doit rester près du cadre, l'appli lancée. Si le cadre s'éteint ou s'éloigne, l'appli se
reconnecte toute seule à la minute suivante. **Arrêter** rend le cadre à l'appli iDotMatrix.

## Pour les développeurs

- `app/src/main/python/pixelmeteo.py` : le côté Python, qui appelle `meteo.py` et `weather.py` de
  l'intégration **sans les modifier** (copiés à la compilation) pour les prévisions et le dessin.
- `Frame.kt` : le Bluetooth, comme `client/connectionManager.py` et `client/modules/gif.py`
  (paquets de 4 Ko avec en-tête de 16 octets, écritures de 509 octets sans réponse, attente du cadre).
- `MeteoService.kt` : le service au premier plan qui envoie chaque minute.
- `MainActivity.kt` + `assets/index.html` : la page de réglages.

Compiler (Linux ou WSL, avec le SDK Android, Gradle 8.10 et Python 3.13 pour Chaquopy) :

```bash
bash android/build_apk.sh
```

Le fichier sort dans `android/dist/PixelMeteo.apk`.
