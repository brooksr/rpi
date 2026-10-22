-- Pi-hole: undo pihole-tv-group.sql and pihole-tv-allow.sql. Blocklists go back
-- to Default (every device); the TV client, the Smart TV list and the TV allow
-- rules are removed. Then: sudo pihole -g, and sudo pihole disable if blocking
-- should stay off for everyone (it was off before).
INSERT OR IGNORE INTO adlist_by_group (adlist_id, group_id)
  SELECT id, 0 FROM adlist WHERE address = 'https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts';
DELETE FROM adlist WHERE address = 'https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt';
DELETE FROM adlist_by_group WHERE group_id = 1;
DELETE FROM domainlist_by_group WHERE domainlist_id IN (SELECT id FROM domainlist WHERE type = 0 AND domain IN ('www.samsungotn.net', 'api.distribution.hulu.com'));
DELETE FROM domainlist WHERE type = 0 AND domain IN ('www.samsungotn.net', 'api.distribution.hulu.com');
DELETE FROM client_by_group WHERE client_id IN (SELECT id FROM client WHERE ip = '@@TV_IP@@');
DELETE FROM client WHERE ip = '@@TV_IP@@';
SELECT 'adlist', a.address, group_concat(ab.group_id) FROM adlist a JOIN adlist_by_group ab ON ab.adlist_id = a.id GROUP BY a.id;
