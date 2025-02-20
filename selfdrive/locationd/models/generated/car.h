#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_2426188779899270877);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_6034937303263587821);
void car_H_mod_fun(double *state, double *out_2579187332183547104);
void car_f_fun(double *state, double dt, double *out_1939839960763914049);
void car_F_fun(double *state, double dt, double *out_4233304103879758867);
void car_h_25(double *state, double *unused, double *out_3837027921546495142);
void car_H_25(double *state, double *unused, double *out_6867692706641622056);
void car_h_24(double *state, double *unused, double *out_5937149318244275864);
void car_H_24(double *state, double *unused, double *out_7338150188684960780);
void car_h_30(double *state, double *unused, double *out_3679841253195365997);
void car_H_30(double *state, double *unused, double *out_6997031653784862126);
void car_h_26(double *state, double *unused, double *out_8642221250876659229);
void car_H_26(double *state, double *unused, double *out_7837548048193873336);
void car_h_27(double *state, double *unused, double *out_8760228644810035973);
void car_H_27(double *state, double *unused, double *out_9171794965585287037);
void car_h_29(double *state, double *unused, double *out_5746359408073709177);
void car_H_29(double *state, double *unused, double *out_7561586381254713546);
void car_h_28(double *state, double *unused, double *out_4684842161238669998);
void car_H_28(double *state, double *unused, double *out_2479187364185182972);
void car_h_31(double *state, double *unused, double *out_7149157387914168149);
void car_H_31(double *state, double *unused, double *out_6837046744764661628);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}