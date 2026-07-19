-- ข้อมูลเดโมสำหรับหน้า prototype (static/index.html) — รันซ้ำได้
-- ลูกค้า 1 + ช่าง 3 คน (ตรงกับตัวละครใน prototype)

INSERT INTO users (line_user_id, role, display_name, tambon_id) VALUES
  ('Udemo-customer', 'customer', 'คุณลูกค้า (เดโม)', 1),
  ('Udemo-bird',     'provider', 'พี่เบิร์ด ตัดหญ้า-จัดสวน', 3),
  ('Udemo-tom',      'provider', 'ช่างต้อม', 1),
  ('Udemo-kampun',   'provider', 'ลุงคำปุ่น', 4)
ON CONFLICT (line_user_id) DO UPDATE
  SET display_name = EXCLUDED.display_name, role = EXCLUDED.role;

INSERT INTO providers (user_id, categories, tambon_coverage, bio, verified,
                       rating_avg, rating_count, jobs_done)
SELECT u.id,
       (SELECT array_agg(id) FROM service_categories),  -- ช่างเดโมรับทุกหมวด
       ARRAY[1, 2, 3, 4, 5],
       v.bio, v.verified, v.avg::numeric, v.cnt, v.done
FROM (VALUES
  ('Udemo-bird',   'เครื่องมือครบ เก็บงานเรียบร้อย', true,  4.80, 98, 98),
  ('Udemo-tom',    'ราคาเป็นกันเอง รวมขนเศษไปทิ้ง',  false, 4.60, 41, 41),
  ('Udemo-kampun', 'งานละเอียด ตัดเรียบเสมอกัน',     true,  5.00, 12, 12)
) AS v(lid, bio, verified, avg, cnt, done)
JOIN users u ON u.line_user_id = v.lid
ON CONFLICT (user_id) DO NOTHING;
