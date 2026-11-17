---
name: reglages
description: Adapte l'agent mail Hermes à la personne - catégories calées sur ses vrais dossiers IMAP, marques ou activités et leur ton, fournisseurs reconnus par domaine, domaines protégés (formulaires du site), base de connaissances Markdown, puis validation et vérification. Déclencheurs - adapter le tri de mes mails, mes dossiers, ajouter un fournisseur, changer le ton des brouillons, brancher mes notes.
---

# Agent mail — réglages

Règles : [regles.md](../../references/regles.md). Lanceur : `bash .ottho-agents/mail …` (absent : étape 0 du skill `installer`). L'agent doit être installé.

Les réglages vivent à deux endroits, jamais avec un secret :
- `mail-agent.yaml` dans le profil : catégories, dossiers, marques, fournisseurs, domaines protégés, base de connaissances, mode.
- `SOUL.md` dans le profil : l'activité de la personne, le ton de chaque marque, ses règles de réponse.

## 1. Lire l'existant

```bash
bash .ottho-agents/mail run config get
bash .ottho-agents/mail run folders
```

Montre-lui ses dossiers réels et les catégories prévues. Une catégorie dont le dossier n'existe pas : soit on renomme la catégorie vers son dossier existant (préféré : on respecte son rangement), soit elle crée le dossier dans son webmail. Ne crée et ne déplace rien dans sa boîte sans son accord.

## 2. Construire avec elle, une question à la fois

1. **Catégories** : garde celles qui servent, retire les autres, ajoute les siennes (clé en minuscules sans espace, `folder` = nom exact du dossier, `description` = ce qui y va, lue par l'agent pour décider). `indesirables` et `autre` restent.
2. **Marques ou activités** : une entrée par activité qui partage la boîte (`label`, `description` d'une phrase, `from_name`, `signature`). Une seule activité : une seule entrée.
3. **Fournisseurs connus** : nom du dossier et domaines d'envoi ; leurs factures, suivis et paiements seront rangés seuls dans `Fournisseurs/<nom>/<type>`.
4. **Domaines protégés** : ses propres domaines (formulaires de contact du site). Un mail authentifié venant d'eux n'est jamais classé indésirable.
5. **Relais de transfert** : seulement si ses adresses passent par un transfert (ex. Cloudflare Email Routing → `cloudflare-email.net`).
6. **Base de connaissances** (facultatif) : un dossier de notes Markdown sur le serveur (services, tarifs publics, procédures, conditions). Les pages marquées `private: true` et les sous-dossiers de `exclude_dirs` ne sont jamais lus. Copie : `bash .ottho-agents/mail run knowledge-sync <dossier sur le serveur>` ; ses notes sont sur son ordinateur : propose de les envoyer d'abord sur le VPS (`scp -r`), elle choisit ce qui part. Jamais de finances, de stratégie ou de données d'autres clients dans la base.

## 3. Écrire, valider, appliquer

Écris le nouveau `mail-agent.yaml` dans un fichier local `.ottho-agents/mail-agent.yaml`, montre-lui le diff en clair (ce qui change, en français), puis après accord :

```bash
bash .ottho-agents/mail run config put < .ottho-agents/mail-agent.yaml
```

`REFUSÉ` : lis la liste des erreurs, corrige, renvoie. `OK` : l'ancienne version est gardée dans `/var/backups/ottho-agents/mail/`. Les catégories, fournisseurs et dossiers sont relus à chaud ; **un changement de marques ou de registres demande une relance de la gateway** : `bash .ottho-agents/mail run restart`, avec son accord (le bot est coupé quelques secondes).

## 4. Le ton : SOUL.md

La section « Mon activité » du `SOUL.md` décrit ses marques, son public, son ton, ses interdits (ex. « jamais de prix par mail »). Rédige-la avec elle en 5 à 10 lignes, sans aucun prix ni promesse (les faits vont dans la base ou se dictent au bot). Lis la version en place (`bash .ottho-agents/mail run soul get`), écris la nouvelle dans `.ottho-agents/SOUL.md` en gardant intactes les sections Sécurité et Rédaction, montre le diff, puis après accord : `bash .ottho-agents/mail run soul put < .ottho-agents/SOUL.md` (copie précédente gardée). Une réinstallation ne l'écrase plus.

## 5. Vérifier

```bash
bash .ottho-agents/mail run test
```

Puis un vrai mail de test dans chaque catégorie qui a changé, et la décision lue sur Telegram. Termine par : ce qui a changé, la preuve, ce qui reste à surveiller pendant le shadow.
