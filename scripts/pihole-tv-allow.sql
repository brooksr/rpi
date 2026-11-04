-- Pi-hole: allow domains for the TV group (id 1) that the TV's blocklists catch
-- but the TV needs. New domains land in Default (group 0) only, which the TV
-- isn't in, so each is also added to TV. Then: sudo pihole reloadlists
--
-- Smart Hub (the Apps screen, app settings, installs and app updates) stops
-- working without the samsungqbe / samsungcloudsolution.net / *pu servers
-- (found in the query log, 2026-11-01). Samsung's ad servers stay blocked:
-- tvx.adgrx.com, config.samsungads.com, sas.samsungcloudsolution.com.
INSERT OR IGNORE INTO domainlist (type, domain, comment) VALUES
  (0, 'www.samsungotn.net', 'Samsung TV software updates'),
  (0, 'api.distribution.hulu.com', 'Hulu playback'),
  (0, 'osb.samsungqbe.com', 'Smart Hub: Apps screen and app store'),
  (0, 'osb-krsvc.samsungqbe.com', 'Smart Hub: Apps screen and app store'),
  (0, 'lcprd1.samsungcloudsolution.net', 'Smart Hub: launcher and app settings'),
  (0, 'notice.samsungcloudsolution.com', 'Smart Hub: notices'),
  (2, '^[a-z]pu\.samsungelectronics\.com$', 'Smart Hub: app downloads and updates (apu ... zpu)'),
  (2, '^osb(-[a-z0-9-]+)?\.samsungqbe\.com$', 'Smart Hub: Apps screen and app store (osb, osb-ussvc, osb-apps, ...)');
INSERT OR IGNORE INTO domainlist_by_group (domainlist_id, group_id)
  SELECT id, 1 FROM domainlist WHERE (type = 0 AND domain IN ('www.samsungotn.net', 'api.distribution.hulu.com',
    'osb.samsungqbe.com', 'osb-krsvc.samsungqbe.com', 'lcprd1.samsungcloudsolution.net', 'notice.samsungcloudsolution.com'))
    OR (type = 2 AND domain IN ('^[a-z]pu\.samsungelectronics\.com$', '^osb(-[a-z0-9-]+)?\.samsungqbe\.com$'));
SELECT d.domain, group_concat(g.group_id) FROM domainlist d JOIN domainlist_by_group g ON g.domainlist_id = d.id GROUP BY d.id;
