/* resource_table_empty.h */
#ifndef _RSC_TABLE_PRU_H_
#define _RSC_TABLE_PRU_H_

#include <stddef.h>
#include <rsc_types.h>

struct my_resource_table {
	struct resource_table base;
	uint32_t offset[1];
};

#pragma DATA_SECTION(resourceTable, ".resource_table")
#pragma RETAIN(resourceTable)
struct my_resource_table resourceTable = {
	1,          /* version */
	0,          /* num of entries */
	{0, 0},     /* reserved fields */
	{0},        /* offsets */
};

#endif /* _RSC_TABLE_PRU_H_ */
