-- Pi-hole: block ads and tracking for the Samsung TV only (see README, "Pi-hole for the Samsung TV only").
-- Needs a group named TV with id 1 (Group Management in the web UI). Then: sudo pihole -g; sudo pihole enable.

INSERT INTO client (ip, comment) VALUES ('@@TV_IP@@', 'Samsung TV');
-- New clients land in Default (group 0); the TV goes in TV (group 1) only.
DELETE FROM client_by_group WHERE group_id = 0 AND client_id = (SELECT id FROM client WHERE ip = '@@TV_IP@@');
INSERT INTO client_by_group (client_id, group_id) SELECT id, 1 FROM client WHERE ip = '@@TV_IP@@';
INSERT INTO adlist (address, comment, type) VALUES ('https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt', 'Smart TV ads and tracking', 0);
-- Both blocklists apply to the TV group only, not Default.
DELETE FROM adlist_by_group WHERE group_id = 0 AND adlist_id IN (SELECT id FROM adlist WHERE address IN ('https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts', 'https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt'));
INSERT INTO adlist_by_group (adlist_id, group_id) SELECT id, 1 FROM adlist WHERE address IN ('https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts', 'https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt');
SELECT 'client', c.ip, group_concat(cb.group_id) FROM client c JOIN client_by_group cb ON cb.client_id = c.id GROUP BY c.id;
SELECT 'adlist', a.address, group_concat(ab.group_id) FROM adlist a JOIN adlist_by_group ab ON ab.adlist_id = a.id GROUP BY a.id;
