#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void live_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_9(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_12(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_35(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_32(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_33(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_H(double *in_vec, double *out_7205012559873777120);
void live_err_fun(double *nom_x, double *delta_x, double *out_3580068722819574247);
void live_inv_err_fun(double *nom_x, double *true_x, double *out_4541387793232587300);
void live_H_mod_fun(double *state, double *out_4631414588385295818);
void live_f_fun(double *state, double dt, double *out_6358523936919490941);
void live_F_fun(double *state, double dt, double *out_49157792372547019);
void live_h_4(double *state, double *unused, double *out_5652399964424206657);
void live_H_4(double *state, double *unused, double *out_4616718418402947756);
void live_h_9(double *state, double *unused, double *out_7364112188567772080);
void live_H_9(double *state, double *unused, double *out_1727856866122868414);
void live_h_10(double *state, double *unused, double *out_3239069402685352308);
void live_H_10(double *state, double *unused, double *out_7296331592882781083);
void live_h_12(double *state, double *unused, double *out_1347033631248870879);
void live_H_12(double *state, double *unused, double *out_3050409895279502736);
void live_h_35(double *state, double *unused, double *out_5713950732179689556);
void live_H_35(double *state, double *unused, double *out_5795972927604516445);
void live_h_32(double *state, double *unused, double *out_1609469360550153100);
void live_H_32(double *state, double *unused, double *out_1118891576089599911);
void live_h_13(double *state, double *unused, double *out_5092052935177841739);
void live_H_13(double *state, double *unused, double *out_7562001660576220248);
void live_h_14(double *state, double *unused, double *out_7364112188567772080);
void live_H_14(double *state, double *unused, double *out_1727856866122868414);
void live_h_33(double *state, double *unused, double *out_8243938974317357979);
void live_H_33(double *state, double *unused, double *out_8946529932243374049);
void live_predict(double *in_x, double *in_P, double *in_Q, double dt);
}