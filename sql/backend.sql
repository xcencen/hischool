
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `username` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '账号',
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '密码',
  `name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '名称',
  `role` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '角色：student-学生，admin-管理员',
  `email` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '邮箱',
  `phone` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '手机号',
  `avatar` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '头像',
  `status` int NOT NULL COMMENT '状态：0-禁用，1-正常',
  `create_time` datetime NOT NULL COMMENT '创建时间',
  `update_time` datetime NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `username`(`username` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '用户信息表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of users
-- ----------------------------
INSERT INTO `users` VALUES (1, 'admin', '$2b$12$ypJClLKejFCsyn2eltOco.YAmXory0HFjh7E/oHu9MBzDZZ6wYSSi', '管理员', 'admin', 'admin@system.cn', '13988776699', '/uploads/1790046856623_dc4830aa.jpg', 1, '2026-09-11 15:30:07', '2026-09-22 11:14:34');
INSERT INTO `users` VALUES (2, 'aaa', '$2a$10$phJ2k4sP5.c7T/LuXwzyTu/AlbbOFXblsAZEW6mIfh3koVxQ3Hhny', '小白', 'student', 'xiaobai@qq.com', '13899776688', '/uploads/1790046891012_452a9884.png', 1, '2026-09-09 16:56:41', '2026-09-22 11:14:52');
INSERT INTO `users` VALUES (3, 'bbb', '$2a$10$blJ4Qgbaqxm5jmUAWvuiRuKy/FiqbmFv.n1i0noM3pxUZrYhd2HNK', '小黑', 'student', 'xiaohei@163.com', '13799886699', '/uploads/1790046917012_b9ee534a.png', 1, '2026-09-22 11:15:00', '2026-09-22 11:15:30');

SET FOREIGN_KEY_CHECKS = 1;
